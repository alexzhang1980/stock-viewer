from flask import Flask, jsonify, render_template_string
import requests
import time
import statistics
import concurrent.futures
import os
from datetime import datetime, timedelta

app = Flask(__name__)

STOCKS = [
    {"name": "中芯国际", "code": "688981", "secid": "1.688981", "sina": "sh688981"},
    {"name": "兆易创新", "code": "603986", "secid": "1.603986", "sina": "sh603986"},
    {"name": "寒武纪", "code": "688256", "secid": "1.688256", "sina": "sh688256"},
    {"name": "北方华创", "code": "002371", "secid": "0.002371", "sina": "sz002371"},
    {"name": "海光信息", "code": "688041", "secid": "1.688041", "sina": "sh688041"},
    {"name": "豪威集团", "code": "603501", "secid": "1.603501", "sina": "sh603501"},
]

CACHE = {"time": 0, "data": None}
CACHE_SECONDS = 10

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json, text/plain, */*"
})

def safe_float(x, div=1):
    try:
        if x is None or x == "-":
            return None
        return round(float(x) / div, 2)
    except:
        return None

def fetch_quote_eastmoney(secid):
    """东方财富实时行情（优先）"""
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f43,f44,f45,f46,f47,f48,f60,f170,f168,f116,f117,f49,f161",
        "_": int(time.time() * 1000),
    }
    try:
        r = session.get(url, params=params, timeout=(5, 10))
        data = r.json().get("data") or {}
    except:
        return None

    pre_close = safe_float(data.get("f60"), 100)
    price = safe_float(data.get("f43"), 100)
    if price is None:
        price = pre_close

    return {
        "price": price,
        "high": safe_float(data.get("f44"), 100),
        "low": safe_float(data.get("f45"), 100),
        "open": safe_float(data.get("f46"), 100),
        "volume": safe_float(data.get("f47")),
        "amount": safe_float(data.get("f48"), 100000000),
        "pre_close": pre_close,
        "pct": safe_float(data.get("f170"), 100),
        "turnover": safe_float(data.get("f168"), 100),
        "float_cap": safe_float(data.get("f117"), 100000000),
        "outer": safe_float(data.get("f49")),
        "inner": safe_float(data.get("f161")),
    }

def fetch_quote_sina(code):
    """新浪财经备用接口"""
    url = f"https://hq.sinajs.cn/list={code}"
    headers = {"Referer": "https://finance.sina.com.cn"}
    try:
        r = requests.get(url, headers=headers, timeout=6)
        r.encoding = "gbk"
        text = r.text
        if not text or "=" not in text:
            return None
        data_str = text.split('"')[1]
        if not data_str:
            return None
        fields = data_str.split(",")
        if len(fields) < 10:
            return None
        open_price = safe_float(fields[1])
        pre_close = safe_float(fields[2])
        price = safe_float(fields[3]) or pre_close
        high = safe_float(fields[4])
        low = safe_float(fields[5])
        pct = round((price - pre_close) / pre_close * 100, 2) if pre_close else 0
        return {
            "price": price,
            "high": high,
            "low": low,
            "open": open_price,
            "volume": None,
            "amount": None,
            "pre_close": pre_close,
            "pct": pct,
            "turnover": None,
            "float_cap": None,
            "outer": None,
            "inner": None,
        }
    except:
        return None

def get_quote(stock):
    """融合行情：东方财富优先，失败用新浪"""
    quote = fetch_quote_eastmoney(stock["secid"])
    if quote and quote.get("price") is not None:
        return quote
    sina_quote = fetch_quote_sina(stock["sina"])
    return sina_quote if sina_quote else {}

def fetch_trend_for_date(secid, date_str):
    """获取指定日期的分时数据"""
    url = "https://push2his.eastmoney.com/api/qt/stock/trends2/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "iscr": "0",
        "iscca": "0",
        "ndays": "1",
        "end": date_str,            # 关键：指定日期
        "_": int(time.time() * 1000),
    }
    try:
        r = session.get(url, params=params, timeout=(5, 10))
        trends = (r.json().get("data") or {}).get("trends") or []
    except:
        return []

    rows = []
    for item in trends:
        p = item.split(",")
        if len(p) >= 8:
            rows.append({
                "time": p[0][-5:],
                "price": safe_float(p[1]),
                "avg": safe_float(p[2]),
                "volume": safe_float(p[5]),
            })
    return rows

def fetch_trend_with_fallback(secid):
    """自动回溯最近交易日，返回 (趋势数据, 实际日期)"""
    # 从今天开始往前找，最多10天
    today = datetime.now()
    for i in range(10):
        date = today - timedelta(days=i)
        date_str = date.strftime("%Y%m%d")
        trend = fetch_trend_for_date(secid, date_str)
        if trend:
            return trend, date_str
    return [], today.strftime("%Y%m%d")  # 实在找不到就用今天空数据

def analyze(quote, trend):
    price = quote.get("price")
    pct = quote.get("pct")
    avg = trend[-1]["avg"] if trend and trend[-1].get("avg") else None

    prices = [x["price"] for x in trend if x.get("price") is not None]
    score = 0
    reasons = []

    if price and avg:
        if price > avg:
            score += 2
            reasons.append("站上均线")
        else:
            score -= 2
            reasons.append("低于均线")

    if pct is not None:
        if pct > 1:
            score += 2
            reasons.append("涨幅较强")
        elif pct < -3:
            score -= 3
            reasons.append("跌幅偏大")
        elif pct < -1:
            score -= 1
            reasons.append("弱势震荡")

    if len(prices) >= 20:
        recent = statistics.mean(prices[-10:])
        earlier = statistics.mean(prices[-30:-20]) if len(prices) >= 30 else statistics.mean(prices[:10])
        if recent > earlier:
            score += 2
            reasons.append("短线回升")
        else:
            score -= 2
            reasons.append("短线走弱")

    outer = quote.get("outer") or 0
    inner = quote.get("inner") or 0
    if outer and inner and outer > inner * 1.2:
        score += 2
        reasons.append("主动买强")
    elif inner and outer and inner > outer * 1.2:
        score -= 2
        reasons.append("主动卖强")

    if score >= 5:
        action = "可小仓试探"
        risk = "中"
    elif score >= 2:
        action = "只观察，不追高"
        risk = "中"
    elif score <= -4:
        action = "不买，继续等"
        risk = "偏高"
    else:
        action = "观望"
        risk = "中性"

    return {
        "score": score,
        "action": action,
        "risk": risk,
        "reasons": reasons or ["数据不足"],
    }

def fetch_one_stock(s):
    try:
        quote = get_quote(s)
        trend, data_date = fetch_trend_with_fallback(s["secid"])
        decision = analyze(quote, trend)
        return {
            "name": s["name"],
            "code": s["code"],
            "quote": quote,
            "trend": trend,
            "decision": decision,
            "data_date": data_date,    # 实际数据日期
            "error": "",
        }
    except Exception as e:
        return {
            "name": s["name"],
            "code": s["code"],
            "quote": {},
            "trend": [],
            "decision": {"score": 0, "action": "数据暂时异常", "risk": "未知", "reasons": ["接口超时或数据源无响应"]},
            "data_date": datetime.now().strftime("%Y%m%d"),
            "error": str(e),
        }

def build_data():
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        result = list(executor.map(fetch_one_stock, STOCKS))

    strong = sum(1 for x in result if x["decision"]["score"] >= 5)
    weak = sum(1 for x in result if x["decision"]["score"] <= -2)
    above_avg = sum(1 for x in result
                    if x["quote"].get("price")
                    and x["trend"]
                    and x["trend"][-1].get("avg")
                    and x["quote"]["price"] > x["trend"][-1]["avg"])

    if strong >= 3 and above_avg >= 3:
        sector_status = "板块有修复，可以重点观察"
    elif weak >= 4:
        sector_status = "板块整体偏弱"
    else:
        sector_status = "板块震荡，等待确认"

    # 统一使用第一只股票的数据日期作为整体板块日期
    common_date = result[0]["data_date"] if result else datetime.now().strftime("%Y%m%d")

    return {
        "time": time.strftime("%H:%M:%S"),
        "data_date": common_date,
        "sector": {
            "status": sector_status,
            "strong": strong,
            "weak": weak,
            "above_avg": above_avg,
        },
        "stocks": result,
    }

@app.route("/api/data")
def api_data():
    now = time.time()
    if CACHE["data"] and now - CACHE["time"] < CACHE_SECONDS:
        return jsonify(CACHE["data"])

    data = build_data()
    CACHE["time"] = now
    CACHE["data"] = data
    return jsonify(data)

HTML = """
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>股票联动监控</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
body{font-family:Arial,"Microsoft YaHei";background:#f3f4f6;margin:0;color:#111827}
.header{background:white;padding:18px 22px;margin-bottom:18px;box-shadow:0 2px 10px #ddd}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;padding:0 14px 30px}
.card{background:white;border-radius:12px;padding:16px;box-shadow:0 2px 10px #ddd}
.name{font-size:22px;font-weight:700}
.code{color:#6b7280;font-size:13px}
.price{font-size:30px;font-weight:800;margin-top:8px}
.red{color:#dc2626}.green{color:#059669}.gray{color:#6b7280}
.chart{height:180px;margin:12px 0}
.info{line-height:1.75;font-size:14px}
.decision{background:#f9fafb;border-radius:10px;padding:12px;margin-top:12px;line-height:1.8}
.big{font-size:26px;font-weight:800}
.tag{display:inline-block;padding:3px 8px;border-radius:8px;background:#e5e7eb;margin-right:6px}
.buy{background:#dcfce7;color:#166534}
.wait{background:#fef9c3;color:#854d0e}
.no{background:#fee2e2;color:#991b1b}
.err{color:#dc2626;font-size:13px}
@media(max-width:1000px){.grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="header">
  <h1>板块状态：<span id="sector">加载中...</span></h1>
  <p>刷新时间：<span id="time">--</span></p>
  <p>数据日期：<span id="dataDate">--</span></p>
  <p>强势股数量：<span id="strong">--</span></p>
  <p>弱势股数量：<span id="weak">--</span></p>
  <p>站上均线数量：<span id="above">--</span></p>
  <p class="err" id="err"></p>
</div>
<div class="grid" id="grid"></div>
<script>
let charts = [];
function renderChart(id, trend){
  const dom = document.getElementById(id);
  if(!dom) return;
  const chart = echarts.init(dom);
  charts.push(chart);
  const times = trend.map(x => x.time);
  const prices = trend.map(x => x.price);
  const avgs = trend.map(x => x.avg);
  chart.setOption({
    animation:false,
    grid:{left:35,right:10,top:10,bottom:25},
    xAxis:{type:'category',data:times,axisLabel:{show:false}},
    yAxis:{type:'value',scale:true,axisLabel:{fontSize:10}},
    tooltip:{trigger:'axis'},
    series:[
      {name:'价格',type:'line',data:prices,smooth:true,symbol:'none',lineStyle:{width:2}},
      {name:'均价',type:'line',data:avgs,smooth:true,symbol:'none',lineStyle:{width:1,type:'dashed'}}
    ]
  });
}

async function loadData(){
  const err = document.getElementById('err');
  err.innerText = '';
  try{
    const res = await fetch('/api/data?t=' + Date.now());
    if(!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();

    document.getElementById('sector').innerText = data.sector.status;
    document.getElementById('time').innerText = data.time;
    document.getElementById('dataDate').innerText = data.data_date || '--';
    document.getElementById('strong').innerText = data.sector.strong;
    document.getElementById('weak').innerText = data.sector.weak;
    document.getElementById('above').innerText = data.sector.above_avg;

    charts.forEach(c => c.dispose());
    charts = [];
    const grid = document.getElementById('grid');
    grid.innerHTML = '';

    data.stocks.forEach((s, i) => {
      const q = s.quote || {};
      const d = s.decision || {};
      const pct = q.pct ?? 0;
      const colorClass = pct >= 0 ? 'red' : 'green';
      let tagClass = 'wait';
      if(d.score >= 5) tagClass = 'buy';
      if(d.score <= -4) tagClass = 'no';

      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = `
        <div class="name">${s.name}</div>
        <div class="code">${s.code}</div>
        <div class="price ${colorClass}">${q.price ?? '--'}</div>
        <div class="${colorClass}">涨幅：${q.pct ?? '--'}%</div>
        <div id="chart${i}" class="chart"></div>
        <div class="info">
          今开：${q.open ?? '--'}　最高：${q.high ?? '--'}　最低：${q.low ?? '--'}<br>
          昨收：${q.pre_close ?? '--'}　成交额：${q.amount ?? '--'}亿<br>
          换手：${q.turnover ?? '--'}%　流通市值：${q.float_cap ?? '--'}亿<br>
          主动买：${q.outer ?? '--'}　主动卖：${q.inner ?? '--'}
        </div>
        <div class="decision">
          <div>评分：<span class="big">${d.score}</span></div>
          <div>操作提示：<span class="tag ${tagClass}">${d.action}</span></div>
          <div>风险：${d.risk}</div>
          <div>判断依据：${(d.reasons || []).join(' / ')}</div>
          ${s.error ? `<div class="err">异常：${s.error}</div>` : ''}
        </div>
      `;
      grid.appendChild(card);
    });

    setTimeout(() => {
      data.stocks.forEach((s, i) => renderChart('chart' + i, s.trend || []));
    }, 150);
  }catch(e){
    err.innerText = '数据加载失败：' + e.message + '。请等待自动刷新。';
  }
}

loadData();
setInterval(loadData, 15000);
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/health")
def health():
    return "ok"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
