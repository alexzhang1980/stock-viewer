from flask import Flask, jsonify, render_template_string, request
import requests
import time
import statistics
import traceback

app = Flask(__name__)

STOCKS = [
    {"name": "中芯国际", "code": "688981", "secid": "1.688981"},
    {"name": "兆易创新", "code": "603986", "secid": "1.603986"},
    {"name": "寒武纪", "code": "688256", "secid": "1.688256"},
    {"name": "北方华创", "code": "002371", "secid": "0.002371"},
    {"name": "海光信息", "code": "688041", "secid": "1.688041"},
    {"name": "豪威集团", "code": "603501", "secid": "1.603501"},
]


def safe_float(x, div=1):
    """安全转换为浮点数，可指定除数"""
    try:
        if x is None or x == "-":
            return None
        return round(float(x) / div, 2)
    except (ValueError, TypeError):
        return None


def fetch_quote(secid):
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f43,f44,f45,f46,f47,f48,f60,f170,f171,f168,f169,f170,f116,f117,f49,f161",
        "_": int(time.time() * 1000),
    }
    r = requests.get(url, params=params, timeout=6)
    data = r.json().get("data") or {}

    # 昨收单独取，用于价格为空时的保底
    pre_close = safe_float(data.get("f60"), 100)
    price = safe_float(data.get("f43"), 100)
    if price is None:
        price = pre_close  # 非交易时段显示昨收

    return {
        "price": price,
        "high": safe_float(data.get("f44"), 100),
        "low": safe_float(data.get("f45"), 100),
        "open": safe_float(data.get("f46"), 100),
        "volume": safe_float(data.get("f47")),          # 手，不除以100
        "amount": safe_float(data.get("f48"), 100000000), # 元转亿
        "pre_close": pre_close,
        "pct": safe_float(data.get("f170"), 100),        # 涨跌幅，已带%
        "turnover": safe_float(data.get("f168"), 100),   # 换手率，%
        "market_cap": safe_float(data.get("f116"), 100000000), # 总市值，元转亿
        "float_cap": safe_float(data.get("f117"), 100000000),  # 流通市值
        "outer": safe_float(data.get("f49")),            # 外盘
        "inner": safe_float(data.get("f161")),           # 内盘
    }


def fetch_trend(secid):
    url = "https://push2his.eastmoney.com/api/qt/stock/trends2/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "iscr": "0",
        "iscca": "0",
        "ndays": "1",
        "_": int(time.time() * 1000),
    }
    r = requests.get(url, params=params, timeout=6)
    trends = (r.json().get("data") or {}).get("trends") or []

    rows = []
    for item in trends:
        p = item.split(",")
        if len(p) >= 8:
            # 时间格式 2026-05-08 09:30:00 -> 取后5位 "09:30"
            time_str = p[0][-5:] if p[0] and len(p[0]) >= 5 else ""
            rows.append({
                "time": time_str,
                "price": safe_float(p[1]),
                "avg": safe_float(p[2]),
                "volume": safe_float(p[5]),
                "amount": safe_float(p[6]),
            })
    return rows


def analyze(stock, quote, trend):
    price = quote.get("price")
    pct = quote.get("pct")
    avg = None
    if trend:
        # 有可能最后几个元素的avg为None，取最后一个有效值
        for point in reversed(trend):
            if point.get("avg") is not None:
                avg = point["avg"]
                break

    prices = [x["price"] for x in trend if x.get("price") is not None]
    score = 0
    reasons = []

    # 均线判断
    if price is not None and avg is not None:
        if price > avg:
            score += 2
            reasons.append("站上均线")
        else:
            score -= 2
            reasons.append("低于均线")

    # 涨跌幅判断
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

    # 短线趋势判断（至少需要20个有效价格点）
    if len(prices) >= 20:
        recent = prices[-10:]
        earlier = prices[-30:-20] if len(prices) >= 30 else prices[:10]
        if statistics.mean(recent) > statistics.mean(earlier):
            score += 2
            reasons.append("短线回升")
        else:
            score -= 2
            reasons.append("短线走弱")

    # 内外盘判断
    outer = quote.get("outer") or 0
    inner = quote.get("inner") or 0
    if outer > inner * 1.2 and outer > 0:
        score += 2
        reasons.append("主动买强")
    elif inner > outer * 1.2 and inner > 0:
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
        "reasons": reasons,
    }


@app.route("/api/data")
def api_data():
    result = []
    for s in STOCKS:
        try:
            quote = fetch_quote(s["secid"])
            trend = fetch_trend(s["secid"])
            decision = analyze(s, quote, trend)
            result.append({
                "name": s["name"],
                "code": s["code"],
                "secid": s["secid"],
                "quote": quote,
                "trend": trend,
                "decision": decision,
            })
        except Exception as e:
            result.append({
                "name": s["name"],
                "code": s["code"],
                "secid": s["secid"],
                "error": str(e),
                "quote": {},
                "trend": [],
                "decision": {"score": 0, "action": "数据异常", "risk": "未知", "reasons": []},
            })

    # 板块统计
    strong = sum(1 for x in result if x["decision"]["score"] >= 5)
    weak = sum(1 for x in result if x["decision"]["score"] <= -2)
    above_avg = sum(
        1 for x in result
        if x["quote"].get("price") is not None
        and x["trend"]
        and (x["quote"]["price"] > (x["trend"][-1].get("avg") or 0))
    )

    if strong >= 3 and above_avg >= 3:
        sector = "板块有修复，可以重点观察"
    elif weak >= 4:
        sector = "板块整体偏弱"
    else:
        sector = "板块震荡，等待确认"

    return jsonify({
        "time": time.strftime("%H:%M:%S"),
        "sector": {
            "status": sector,
            "strong": strong,
            "weak": weak,
            "above_avg": above_avg,
        },
        "stocks": result,
    })


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
@media(max-width:1000px){.grid{grid-template-columns:1fr}}
</style>
</head>
<body>

<div class="header">
  <h1>板块状态：<span id="sector">加载中...</span></h1>
  <p>刷新时间：<span id="time">--</span></p>
  <p>强势股数量：<span id="strong">--</span></p>
  <p>弱势股数量：<span id="weak">--</span></p>
  <p>站上均线数量：<span id="above">--</span></p>
</div>

<div class="grid" id="grid"></div>

<script>
async function loadData(){
  const res = await fetch('/api/data?t=' + Date.now());
  const data = await res.json();

  document.getElementById('sector').innerText = data.sector.status;
  document.getElementById('time').innerText = data.time;
  document.getElementById('strong').innerText = data.sector.strong;
  document.getElementById('weak').innerText = data.sector.weak;
  document.getElementById('above').innerText = data.sector.above_avg;

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

    const div = document.createElement('div');
    div.className = 'card';
    div.innerHTML = `
      <div class="name">${s.name}</div>
      <div class="code">${s.code}</div>
      <div class="price ${colorClass}">${q.price ?? '--'}</div>
      <div class="${colorClass}">涨幅：${q.pct ?? '--'}%</div>
      <div id="chart${i}" class="chart"></div>

      <div class="info">
        今开：${q.open ?? '--'}　最高：${q.high ?? '--'}　最低：${q.low ?? '--'}<br>
        昨收：${q.pre_close ?? '--'}　成交额：${q.amount ?? '--'}亿<br>
        换手：${q.turnover ?? '--'}%　流通市值：${q.float_cap ?? '--'}亿
      </div>

      <div class="decision">
        <div>评分：<span class="big">${d.score}</span></div>
        <div>操作提示：<span class="tag ${tagClass}">${d.action}</span></div>
        <div>风险：${d.risk}</div>
        <div>判断依据：${(d.reasons || []).join(' / ') || '暂无'}</div>
        ${s.error ? `<div style="color:red;margin-top:4px;">异常：${s.error}</div>` : ''}
      </div>
    `;
    grid.appendChild(div);

    const chart = echarts.init(document.getElementById('chart'+i));
    const times = (s.trend || []).map(x => x.time);
    const prices = (s.trend || []).map(x => x.price);
    const avgs = (s.trend || []).map(x => x.avg);

    chart.setOption({
      animation:false,
      grid:{left:35,right:10,top:10,bottom:25},
      xAxis:{type:'category',data:times,axisLabel:{show:false}},
      yAxis:{type:'value',scale:true,axisLabel:{fontSize:10}},
      series:[
        {name:'价格',type:'line',data:prices,smooth:true,symbol:'none',lineStyle:{width:2}},
        {name:'均价',type:'line',data:avgs,smooth:true,symbol:'none',lineStyle:{width:1,type:'dashed'}}
      ],
      tooltip:{trigger:'axis'}
    });
  });
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
