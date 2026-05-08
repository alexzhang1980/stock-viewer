import os
import requests
from flask import Flask, jsonify, render_template_string, request
import pandas as pd
from datetime import datetime, timedelta
import akshare as ak

app = Flask(__name__)

# ========== 工具函数 ==========
def code_to_eastmoney_secid(code):
    code = code.lower()
    if code.startswith('sh'):
        return f"1.{code[2:]}"
    elif code.startswith('sz'):
        return f"0.{code[2:]}"
    else:
        market = '1' if code.startswith('6') else '0'
        return f"{market}.{code}"

def normalize_symbol(code):
    return code.replace('.', '').replace('sz', '').replace('SZ', '').replace('sh', '').replace('SH', '')

# ========== 单股详情页 API（不变） ==========
@app.route('/api/quote/<code>')
def quote_detail(code):
    secid = code_to_eastmoney_secid(code)
    try:
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        fields = ('f43,f44,f45,f46,f47,f48,f50,f57,f58,f60,f169,f170,'
                  'f19,f20,f21,f22,f23,f24,f25,f26,f27,f28,f29,f30,f31,f32,f33,f34,f35,f36,f37')
        params = {'secid': secid, 'fields': fields, 'invt': '2', 'fltt': '2'}
        h = {'Referer': 'https://quote.eastmoney.com/'}
        r = requests.get(url, params=params, headers=h, timeout=5)
        d = r.json().get('data', {})
        if not d:
            return jsonify({"error": "no data"}), 404
        def p(field): return d.get(field, 0) / 100 if d.get(field) else 0
        def vol(field): return int(d.get(field, 0) or 0)
        buy5 = [
            {"price": p('f19'), "volume": vol('f20')},
            {"price": p('f21'), "volume": vol('f22')},
            {"price": p('f23'), "volume": vol('f24')},
            {"price": p('f25'), "volume": vol('f26')},
            {"price": p('f27'), "volume": vol('f28')},
        ]
        sell5 = [
            {"price": p('f29'), "volume": vol('f30')},
            {"price": p('f31'), "volume": vol('f32')},
            {"price": p('f33'), "volume": vol('f34')},
            {"price": p('f35'), "volume": vol('f36')},
            {"price": p('f37'), "volume": vol('f38')},
        ]
        return jsonify({
            "name": d.get('f58', ''),
            "price": p('f43'),
            "last_close": p('f60'),
            "volume": d.get('f47', 0),
            "amount": d.get('f48', 0),
            "volume_ratio": d.get('f50', 0) / 100 if d.get('f50') else 0,
            "buy5": buy5,
            "sell5": sell5
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/minute_kline/<code>')
def minute_kline(code):
    secid = code_to_eastmoney_secid(code)
    today = datetime.now().strftime('%Y%m%d')
    try:
        url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57',
            'klt': '1', 'fqt': '0', 'end': today, 'lmt': '240'
        }
        h = {'Referer': 'https://quote.eastmoney.com/'}
        r = requests.get(url, params=params, headers=h, timeout=5)
        res = r.json()
        if res.get('data') and res['data'].get('klines'):
            lines = res['data']['klines']
            data = []
            for line in lines:
                parts = line.split(',')
                if len(parts) >= 7:
                    data.append({
                        'time': parts[0][-8:][:5],
                        'close': float(parts[2]),
                        'volume': int(parts[5]),
                        'amount': float(parts[6])
                    })
            return jsonify({"success": True, "data": data})
        else:
            return jsonify({"error": "no data"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/tick_data/<code>')
def tick_data(code):
    symbol = normalize_symbol(code)
    try:
        df = ak.stock_zh_a_tick_tx_js(symbol=symbol)
        if df is None or df.empty:
            return jsonify({"error": "no data"}), 404
        records = []
        prev_dir = None
        cnt = 0
        for _, row in df.iterrows():
            t = str(row.get('成交时间', ''))
            price = float(row.get('成交价格', 0))
            vol = int(row.get('成交量', 0))
            nature = row.get('性质', '')
            direction = 'B' if '买' in str(nature) else 'S'
            is_big = vol >= 500
            if direction == prev_dir:
                cnt += 1
            else:
                cnt = 1
                prev_dir = direction
            consecutive = cnt >= 3
            records.append({
                '时间': t,
                '价格': price,
                '成交': vol,
                '方向': direction,
                '超大单': is_big,
                '连续': consecutive
            })
        return jsonify(records)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/adv_stats/<code>')
def adv_stats(code):
    symbol = normalize_symbol(code)
    try:
        df = ak.stock_zh_a_tick_tx_js(symbol=symbol)
        if df is None or df.empty:
            return jsonify({"error": "no data"}), 404
        df['性质'] = df['性质'].astype(str)
        df['方向'] = df['性质'].apply(lambda x: 'B' if '买' in x else 'S')
        df['成交量'] = pd.to_numeric(df['成交量'], errors='coerce').fillna(0)
        df['时间'] = pd.to_datetime(df['成交时间'], format='%H:%M:%S')
        now = df['时间'].max()
        five_min_ago = now - pd.Timedelta(minutes=5)
        recent = df[(df['时间'] >= five_min_ago) & (df['时间'] <= now)]
        net5 = int(recent[recent['方向'] == 'B']['成交量'].sum() - recent[recent['方向'] == 'S']['成交量'].sum())
        buy_vol = df[df['方向'] == 'B']['成交量'].sum()
        sell_vol = df[df['方向'] == 'S']['成交量'].sum()
        ratio = round(buy_vol / sell_vol, 2) if sell_vol != 0 else 0
        big_vol = df[df['成交量'] >= 500]['成交量'].sum()
        total_vol = df['成交量'].sum()
        big_ratio = round(big_vol / total_vol * 100, 1) if total_vol > 0 else 0
        df['连续组'] = (df['方向'] != df['方向'].shift()).cumsum()
        groups = df[df['方向'] == 'B'].groupby('连续组').agg({'成交量': 'sum'})
        max_cons = int(groups['成交量'].max()) if not groups.empty else 0
        return jsonify({
            '5分钟净流入': net5,
            '主动买/卖比': ratio,
            '大单占比': big_ratio,
            '连续买单最大量': max_cons
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============================================================
# 仪表盘模板（满足你所有要求）
# ============================================================
HTML_DASHBOARD = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>半导体六股联动监控台</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
body{margin:0;font-family:Arial,"Microsoft YaHei";background:#f3f4f6;color:#111827}
header{padding:14px 20px;background:#111827;color:#fff;font-size:20px;font-weight:bold}
#time{font-size:13px;color:#9ca3af;margin-top:4px}
#sector-panel{background:#fff;margin:10px 12px;padding:12px;border-radius:10px;box-shadow:0 2px 6px rgba(0,0,0,0.08);line-height:1.8}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;padding:12px}
.card{background:#fff;border-radius:12px;padding:12px;box-shadow:0 2px 8px rgba(0,0,0,.08)}
.name{font-size:18px;font-weight:bold}
.code{color:#6b7280;font-size:13px}
.price{font-size:24px;font-weight:bold;margin-top:6px}
.red{color:#dc2626}.green{color:#16a34a}.orange{color:#f97316}.gray{color:#6b7280}
.chart{height:160px;width:100%;margin-top:8px}
.info{font-size:13px;line-height:1.8;margin-top:8px}
.decision{margin-top:8px;padding:8px;border-radius:8px;background:#f9fafb;font-size:13px;line-height:1.7}
footer{padding:12px 20px;font-size:13px;color:#6b7280}
@media(max-width:1000px){.grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:650px){.grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
  半导体六股联动监控台
  <div id="time">等待刷新...</div>
</header>

<!-- 顶部板块状态区 -->
<div id="sector-panel">
  加载中...
</div>

<div class="grid" id="grid"></div>

<footer>
自动刷新：15秒一次。评分越高越强；低于5分原则上不追。当前版本适合辅助观察，不等于自动买卖建议。
</footer>

<script>
const stocks=[
  {code:"sh688981",name:"中芯国际",secid:"1.688981"},
  {code:"sh603986",name:"兆易创新",secid:"1.603986"},
  {code:"sh688256",name:"寒武纪",secid:"1.688256"},
  {code:"sz002371",name:"北方华创",secid:"0.002371"},
  {code:"sh688041",name:"海光信息",secid:"1.688041"},
  {code:"sh603501",name:"豪威集团",secid:"1.603501"}
];

let allCharts = {};
function destroyAllCharts() {
  Object.keys(allCharts).forEach(key => {
    if (allCharts[key]) {
      allCharts[key].dispose();
      delete allCharts[key];
    }
  });
}

function money(v){
  if(!v) return "--";
  if(v>=1e8) return (v/1e8).toFixed(2)+"亿";
  if(v>=1e4) return (v/1e4).toFixed(2)+"万";
  return v;
}

async function getJson(url){
  const r = await fetch(url + "&_=" + Date.now(), {cache:"no-store"});
  return await r.json();
}

async function fetchBase(s){
  const url = `https://push2.eastmoney.com/api/qt/stock/get?secid=${s.secid}&fields=f43,f44,f45,f46,f47,f48,f60,f169,f170,f171`;
  const j = await getJson(url);
  const d = j.data || {};
  return {
    ...s,
    price: d.f43 / 100,
    high: d.f44 / 100,
    low: d.f45 / 100,
    open: d.f46 / 100,
    volume: d.f47,
    amount: d.f48,
    prev: d.f60 / 100,
    change: d.f169 / 100,
    pct: d.f170 / 100,
    amp: d.f171 / 100,
    volumeRatio: 0,
    activeBuy: 0, activeSell: 0,
    bigBuyCount: 0, bigSellCount: 0,
    bigBuyAmount: 0, bigSellAmount: 0,
    avgPrice: 0
  };
}

async function fetchMinute(s){
  const url = `https://push2his.eastmoney.com/api/qt/stock/trends2/get?secid=${s.secid}&fields1=f1,f2,f3,f4,f5,f6,f7,f8&fields2=f51,f52,f53,f54,f55,f56,f57,f58`;
  const j = await getJson(url);
  const arr = j.data?.trends || [];
  return arr.map(x => {
    const a = x.split(",");
    return {
      time: a[0],
      price: Number(a[1]),
      avg: Number(a[2]),
      volume: Number(a[5])
    };
  }).filter(x => x.price > 0);
}

// ========== 交易决策增强模块 ==========
function analyzeStock(stock, minutes) {
  if (minutes && minutes.length > 0) {
    stock.avgPrice = minutes[minutes.length - 1].avg;
  }
  const { price, avgPrice, pct, volumeRatio } = stock;
  let activeBuy = stock.activeBuy || 0, activeSell = stock.activeSell || 0;
  let bigBuyAmount = stock.bigBuyAmount || 0, bigSellAmount = stock.bigSellAmount || 0;

  const buySellDiff = activeBuy - activeSell;
  const bigOrderDiff = bigBuyAmount - bigSellAmount;
  const avgDeviation = avgPrice ? ((price - avgPrice) / avgPrice) * 100 : 0;

  let score = 0, trend = "", risk = "", action = "";

  if (price > avgPrice) score += 2; else score -= 2;

  if (buySellDiff > 0) score += 2; else if (buySellDiff < 0) score -= 2;

  if (bigOrderDiff > 0) score += 2; else if (bigOrderDiff < 0) score -= 2;

  if (volumeRatio >= 1.5 && buySellDiff > 0) score += 2;
  if (volumeRatio >= 1.5 && buySellDiff < 0) score -= 2;

  if (pct < -2 && price >= avgPrice && buySellDiff > 0) score += 1;

  if (price < avgPrice && bigOrderDiff < 0) risk = "偏弱";
  else if (price > avgPrice && buySellDiff > 0) risk = "可观察";
  else risk = "中性";

  if (score >= 5) trend = "强势回流";
  else if (score >= 2) trend = "企稳偏强";
  else if (score >= -1) trend = "震荡观察";
  else trend = "弱势回避";

  if (score >= 6) action = "可小仓试探";
  else if (score >= 3) action = "等待回踩确认";
  else action = "继续持有观察";

  return {
    ...stock,
    score,
    buySellDiff,
    bigOrderDiff,
    avgDeviation: avgDeviation.toFixed(2),
    trend,
    risk,
    action,
  };
}

// ========== 板块联动评分 ==========
function analyzeSector(analyzedStocks) {
  const strongCount = analyzedStocks.filter(s => s.score >= 3).length;
  const weakCount = analyzedStocks.filter(s => s.score <= -2).length;
  const aboveAvgCount = analyzedStocks.filter(s => s.price > s.avgPrice).length;
  const positiveBuyCount = analyzedStocks.filter(s => s.buySellDiff > 0).length;

  let sectorSignal = "";
  if (strongCount >= 3 && positiveBuyCount >= 3) sectorSignal = "板块资金回流";
  else if (weakCount >= 3) sectorSignal = "板块整体偏弱";
  else if (aboveAvgCount >= 3) sectorSignal = "板块有企稳迹象";
  else sectorSignal = "板块震荡观察";

  return { sectorSignal, strongCount, weakCount, aboveAvgCount, positiveBuyCount };
}

// ========== 卡片生成（按要求展示字段） ==========
function cardHtml(stock) {
  const c = stock.pct >= 0 ? "red" : "green";
  const actionClass = stock.score >= 6 ? "red" : stock.score >= 3 ? "orange" : "green";
  return `
  <div class="card">
    <div class="name">${stock.name}</div>
    <div class="code">${stock.code}</div>
    <div class="price ${c}">${isFinite(stock.price) ? stock.price.toFixed(2) : "--"}</div>
    <div class="${c}">涨幅：${isFinite(stock.pct) ? stock.pct.toFixed(2) : "--"}%</div>
    <div class="chart" id="chart-${stock.code}"></div>
    <div class="info">
      当前价：${stock.price?.toFixed(2) ?? "--"}<br>
      今开：${stock.open?.toFixed(2) ?? "--"}　
      最高：${stock.high?.toFixed(2) ?? "--"}　
      最低：${stock.low?.toFixed(2) ?? "--"}<br>
      昨收：${stock.prev?.toFixed(2) ?? "--"}　
      成交额：${money(stock.amount)}
    </div>
    <div class="decision">
      <p>评分：<b>${stock.score}</b></p>
      <p>操作提示：<span class="${actionClass}"><b>${stock.action}</b></span></p>
      <p>风险：${stock.risk}</p>
      <p>分时趋势：${stock.trend}</p>
      <p>均价偏离：${stock.avgDeviation}%</p>
      <p>主动买卖差：${stock.buySellDiff}手</p>
      <p>大单净额：${stock.bigOrderDiff}手</p>
    </div>
  </div>`;
}

// ========== 图表绘制 ==========
function drawChart(s, m) {
  const el = document.getElementById(`chart-${s.code}`);
  if (!el) return;
  if (el.clientWidth === 0 || el.clientHeight === 0) {
    setTimeout(() => drawChart(s, m), 100);
    return;
  }
  if (allCharts[s.code]) {
    allCharts[s.code].dispose();
  }
  const chart = echarts.init(el);
  allCharts[s.code] = chart;
  const times = m.map(x => x.time.slice(11, 16));
  const prices = m.map(x => x.price);
  const avgs = m.map(x => x.avg);
  chart.setOption({
    animation: false,
    grid: { left: 8, right: 8, top: 10, bottom: 10 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: times, show: false },
    yAxis: { type: 'value', scale: true, show: false },
    series: [
      { name: '价格', type: 'line', data: prices, showSymbol: false, smooth: true, lineStyle: { width: 1.6 }, areaStyle: { opacity: 0.12 } },
      { name: '均价', type: 'line', data: avgs, showSymbol: false, smooth: true, lineStyle: { width: 1, type: 'dashed' } }
    ]
  });
  setTimeout(() => chart.resize(), 50);
}

// ========== 主加载 ==========
async function load(){
  const grid = document.getElementById("grid");
  destroyAllCharts();

  const analyzedList = [];
  const minuteMap = {};

  for (const s of stocks) {
    try {
      const base = await fetchBase(s);
      const minute = await fetchMinute(s);
      const analyzed = analyzeStock(base, minute);
      analyzedList.push(analyzed);
      minuteMap[s.code] = minute;
    } catch (e) {
      analyzedList.push({ error: true, name: s.name, code: s.code });
    }
  }

  // 板块信号
  const validStocks = analyzedList.filter(s => !s.error);
  const sector = analyzeSector(validStocks);
  document.getElementById("sector-panel").innerHTML = `
    <h2 style="margin:0 0 6px">板块状态：${sector.sectorSignal}</h2>
    <p style="margin:2px 0">强势股数量：${sector.strongCount}</p>
    <p style="margin:2px 0">弱势股数量：${sector.weakCount}</p>
    <p style="margin:2px 0">站上均价线数量：${sector.aboveAvgCount}</p>
    <p style="margin:2px 0">主动买入占优数量：${sector.positiveBuyCount}</p>
  `;

  // 生成卡片
  let html = '';
  for (const stock of analyzedList) {
    if (stock.error) {
      html += `<div class="card"><div class="name">${stock.name}</div><div class="code">${stock.code}</div><div class="green">数据读取失败，等待下次刷新</div></div>`;
    } else {
      html += cardHtml(stock);
    }
  }
  grid.innerHTML = html;

  // 画图
  requestAnimationFrame(() => {
    validStocks.forEach(stock => {
      drawChart(stock, minuteMap[stock.code]);
    });
  });

  document.getElementById("time").innerText = "最后刷新：" + new Date().toLocaleTimeString();
}

window.addEventListener("resize", () => {
  Object.keys(allCharts).forEach(key => {
    if (allCharts[key]) allCharts[key].resize();
  });
});

load();
setInterval(load, 15000);
</script>
</body>
</html>
"""

# ============================================================
# 单股详情页模板（不变）
# ============================================================
HTML_STOCK_DETAIL = r"""
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>股票详情</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <style>
        body{font-family:Arial;margin:20px}
        #search-box{margin-bottom:10px}
        .quote-panel{display:flex; gap:20px; margin:10px 0; padding:10px; background:#f9f9f9; border-radius:8px}
        .grid2{display:grid; grid-template-columns:1fr 1fr; gap:15px}
        .section{margin-top:20px}
        table{width:100%; border-collapse:collapse}
        th,td{padding:4px 8px; border-bottom:1px solid #eee}
        .big-tick{font-weight:bold; background:#fff3cd}
        .consecutive-tick{background:#e8f0fe}
    </style>
</head>
<body>
    <div id="search-box"><input id="codeInput" placeholder="sh688981"><button onclick="switchStock()">查询</button></div>
    <h2 id="stockTitle"></h2>
    <div id="quoteDetail" class="quote-panel"></div>
    <div id="minuteChart" style="width:100%;height:350px"></div>
    <div class="section"><h3>五档盘口</h3><div id="orderBook"></div></div>
    <div class="section"><h3>资金强度</h3><div id="advStats"></div></div>
    <div class="section"><h3>分时成交明细（红B/绿S，超大单加粗黄底，连续3单浅蓝底）</h3>
        <div style="max-height:400px;overflow-y:auto"><table id="tickTable"></table></div>
    </div>
    <script>
        let code = window.location.pathname.split('/stock/')[1] || 'sh688981';
        let minuteChart = echarts.init(document.getElementById('minuteChart'));
        async function loadAll(){
            document.getElementById('codeInput').value = code;
            await loadQuote();
            await loadMinuteKline();
            await loadOrderBook();
            await loadTicks();
            await loadAdvStats();
        }
        async function switchStock(){
            code = document.getElementById('codeInput').value.trim().toLowerCase();
            window.history.pushState(null,null,'/stock/'+code);
            await loadAll();
        }
        async function loadQuote(){
            const r = await fetch('/api/quote/'+code);
            const d = await r.json();
            if(!d.error){
                document.getElementById('stockTitle').innerText = `${d.name} (${code})`;
                document.getElementById('quoteDetail').innerHTML = `最新价:${d.price} 涨幅:${((d.price-d.last_close)/d.last_close*100).toFixed(2)}% 量比:${d.volume_ratio}`;
            }
        }
        async function loadMinuteKline(){
            const r = await fetch('/api/minute_kline/'+code);
            const j = await r.json();
            if(j.success){
                const prices = j.data.map(d=>d.close);
                const volumes = j.data.map(d=>d.volume);
                minuteChart.setOption({
                    grid:[{left:'10%',right:'8%',top:'10%',height:'50%'},{left:'10%',right:'8%',top:'65%',height:'25%'}],
                    xAxis:[{data:j.data.map(d=>d.time)},{data:j.data.map(d=>d.time),show:false}],
                    yAxis:[{scale:true},{scale:true}],
                    series:[{type:'line',data:prices,smooth:true,symbol:'none'},{type:'bar',data:volumes}]
                });
            }
        }
        async function loadOrderBook(){
            const r = await fetch('/api/quote/'+code);
            const d = await r.json();
            if(!d.error){
                let html = '<div class="grid2">';
                html += '<div><h4>买盘</h4><table><tr><th>价格</th><th>数量(手)</th></tr>';
                if(d.buy5) d.buy5.forEach(b => html += `<tr><td>${b.price.toFixed(2)}</td><td>${b.volume}</td></tr>`);
                html += '</table></div>';
                html += '<div><h4>卖盘</h4><table><tr><th>价格</th><th>数量(手)</th></tr>';
                if(d.sell5) d.sell5.forEach(s => html += `<tr><td>${s.price.toFixed(2)}</td><td>${s.volume}</td></tr>`);
                html += '</table></div>';
                document.getElementById('orderBook').innerHTML = html;
            }
        }
        async function loadTicks(){
            const r = await fetch('/api/tick_data/'+code);
            const ticks = await r.json();
            let html = '<thead><tr><th>时间</th><th>价格</th><th>成交(手)</th><th>性质</th></tr></thead><tbody>';
            if(Array.isArray(ticks)){
                ticks.forEach(t => {
                    let cls = t['方向']=='B' ? 'color:#e74c3c' : 'color:#2ecc71';
                    if (t['超大单']) cls += ' big-tick';
                    if (t['连续']) cls += ' consecutive-tick';
                    html += `<tr style="${cls}"><td>${t['时间']}</td><td>${t['价格']}</td><td>${t['成交']}</td><td>${t['方向']}</td></tr>`;
                });
            }
            html += '</tbody>';
            document.getElementById('tickTable').innerHTML = html;
        }
        async function loadAdvStats(){
            const r = await fetch('/api/adv_stats/'+code);
            const d = await r.json();
            if(!d.error){
                document.getElementById('advStats').innerHTML = `5分钟净流入:${d['5分钟净流入']}手 | 主动买/卖比:${d['主动买/卖比']} | 大单占比:${d['大单占比']}% | 连续买单最大量:${d['连续买单最大量']}`;
            }
        }
        window.onload = loadAll;
    </script>
</body>
</html>
"""

# ========== 路由 ==========
@app.route("/")
def index():
    return render_template_string(HTML_DASHBOARD)

@app.route("/dashboard")
def dashboard():
    return render_template_string(HTML_DASHBOARD)

@app.route("/stock/<code>")
def stock_detail(code):
    return render_template_string(HTML_STOCK_DETAIL)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
