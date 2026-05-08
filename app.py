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

# ========== 单股详情页所需 API（不变） ==========
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
# 全新仪表盘模板（基于你的 React 组件逻辑用原生 JS 实现）
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

<div id="sector-panel">加载中...</div>
<div class="grid" id="grid"></div>
<footer>自动刷新：30秒一次。评分越高越强；低于5分原则上不追。当前版本适合辅助观察，不等于自动买卖建议。</footer>
<script>
const stocks=[
  {name:"中芯国际",code:"688981",secid:"1.688981"},
  {name:"兆易创新",code:"603986",secid:"1.603986"},
  {name:"寒武纪",code:"688256",secid:"1.688256"},
  {name:"北方华创",code:"002371",secid:"0.002371"},
  {name:"海光信息",code:"688041",secid:"1.688041"},
  {name:"豪威集团",code:"603501",secid:"1.603501"}
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

function formatMoney(value) {
  if (!value && value !== 0) return "--";
  const abs = Math.abs(value);
  if (abs >= 100000000) return (value / 100000000).toFixed(2) + "亿";
  if (abs >= 10000) return (value / 10000).toFixed(2) + "万";
  return value.toFixed(0);
}

function getColor(value) {
  if (value > 0) return "#e11d48";
  if (value < 0) return "#16a34a";
  return "#333";
}

async function getJson(url){
  const r = await fetch(url + "&_=" + Date.now(), {cache:"no-store"});
  return await r.json();
}

// 基础行情（含昨收、涨跌幅等）
async function fetchBase(s){
  const url = `https://push2.eastmoney.com/api/qt/stock/get?secid=${s.secid}&fields=f43,f44,f45,f46,f47,f48,f49,f50,f57,f58,f60,f168,f170`;
  const j = await getJson(url);
  const d = j.data || {};
  return {
    ...s,
    price: d.f43 ? d.f43 / 100 : 0,
    high: d.f44 ? d.f44 / 100 : 0,
    low: d.f45 ? d.f45 / 100 : 0,
    open: d.f46 ? d.f46 / 100 : 0,
    amount: d.f48 || 0,
    yesterday: d.f60 ? d.f60 / 100 : 0,
    changePercent: d.f170 ? d.f170 / 100 : 0,
  };
}

// 分时数据
async function fetchMinute(s){
  const url = `https://push2his.eastmoney.com/api/qt/stock/trends2/get?secid=${s.secid}&fields1=f1,f2,f3,f4,f5,f6,f7,f8&fields2=f51,f52,f53,f54,f55,f56,f57,f58`;
  const j = await getJson(url);
  const arr = j.data?.trends || [];
  return arr.map(x => {
    const a = x.split(",");
    return {
      time: a[0]?.slice(11,16),
      price: Number(a[2]),      // 根据你的 React 代码，price 用 a[2]
      avg: Number(a[7]),        // avg 用 a[7]
      volume: Number(a[5]),
      amount: Number(a[6])
    };
  }).filter(x => x.price > 0);
}

// 主动买卖统计（使用东方财富 details/get 接口）
async function fetchDetails(s){
  const url = `https://push2.eastmoney.com/api/qt/stock/details/get?secid=${s.secid}&fields1=f1,f2,f3,f4&fields2=f51,f52,f53,f54,f55`;
  const j = await getJson(url);
  const details = j.data?.details || [];

  let activeBuy = 0, activeSell = 0, bigBuy = 0, bigSell = 0;

  details.forEach(item => {
    const a = item.split(",");
    if (a.length < 5) return;
    const price = Number(a[1]);
    const volume = Number(a[2]);   // 手
    const direction = Number(a[4]); // 2=主动买，1=主动卖
    const money = price * volume * 100;  // 金额（元）

    if (direction === 2) {
      activeBuy += money;
      if (money >= 500000) bigBuy += money;   // 大单阈值50万元
    } else if (direction === 1) {
      activeSell += money;
      if (money >= 500000) bigSell += money;
    }
  });

  return {
    activeBuy,
    activeSell,
    buySellDiff: activeBuy - activeSell,
    bigBuy,
    bigSell,
    bigOrderDiff: bigBuy - bigSell,
  };
}

// 分析函数（完全照搬 React 组件逻辑）
function analyzeStock(stock, chartData) {
  let score = 0;
  let trend = "弱势观察";
  let action = "继续观察";
  let risk = "中性";

  const latest = chartData?.[chartData.length - 1];
  const avg = latest?.avg || 0;

  if (stock.changePercent > 1) score += 2;
  if (stock.changePercent > 3) score += 2;
  if (stock.changePercent < -2) score -= 2;
  if (stock.changePercent < -4) score -= 2;

  if (stock.price > avg && avg > 0) score += 2;
  if (stock.price < avg && avg > 0) score -= 2;

  if (stock.buySellDiff > 0) score += 2;
  if (stock.buySellDiff < 0) score -= 2;

  if (stock.bigOrderDiff > 0) score += 2;
  if (stock.bigOrderDiff < 0) score -= 2;

  if (score >= 5) {
    trend = "强势";
    action = "可重点观察";
    risk = "偏低";
  } else if (score >= 2) {
    trend = "转强观察";
    action = "等待回踩确认";
    risk = "中性";
  } else if (score <= -4) {
    trend = "弱势回避";
    action = "不买，继续等";
    risk = "偏高";
  }

  return { score, trend, action, risk, avg };
}

// 板块统计
function calcSector(stocksData) {
  const strong = stocksData.filter(s => s.score >= 5).length;
  const weak = stocksData.filter(s => s.score <= -4).length;
  const aboveAvg = stocksData.filter(s => s.price > s.avg).length;
  const activeBuyDom = stocksData.filter(s => s.buySellDiff > 0).length;

  let signal = "";
  if (strong >= 3) signal = "板块转强";
  else if (weak >= 4) signal = "板块整体偏弱";
  else signal = "板块震荡观察";

  return { signal, strong, weak, aboveAvg, activeBuyDom };
}

// 卡片 HTML
function cardHtml(stock, analysis) {
  const color = getColor(stock.changePercent);
  const actionColor = analysis.score >= 5 ? "#e11d48" : analysis.score >= 2 ? "#f97316" : "#16a34a";
  return `
  <div class="card">
    <div class="name">${stock.name}</div>
    <div class="code">${stock.code}</div>
    <div class="price" style="color:${color}">${stock.price?.toFixed(2)}</div>
    <div style="color:${color}">涨幅：${stock.changePercent?.toFixed(2)}%</div>
    <div class="chart" id="chart-${stock.code}"></div>
    <div class="info">
      <div>今开：${stock.open?.toFixed(2)}</div>
      <div>最高：${stock.high?.toFixed(2)}</div>
      <div>最低：${stock.low?.toFixed(2)}</div>
      <div>昨收：${stock.yesterday?.toFixed(2)}</div>
      <div>成交额：${formatMoney(stock.amount)}</div>
      <div>均价：${analysis.avg > 0 ? analysis.avg.toFixed(2) : "--"}</div>
    </div>
    <div class="decision">
      <div>评分：${analysis.score}</div>
      <div>操作提示：<span style="font-weight:bold;color:${actionColor}">${analysis.action}</span></div>
      <div>风险：${analysis.risk}</div>
      <div>分时趋势：${analysis.trend}</div>
      <div style="color:${getColor(stock.buySellDiff)}">主动买卖差：${formatMoney(stock.buySellDiff)}</div>
      <div style="color:${getColor(stock.bigOrderDiff)}">大单净额：${formatMoney(stock.bigOrderDiff)}</div>
      <div>主动买：${formatMoney(stock.activeBuy)} / 主动卖：${formatMoney(stock.activeSell)}</div>
      <div>大单买：${formatMoney(stock.bigBuy)} / 大单卖：${formatMoney(stock.bigSell)}</div>
    </div>
  </div>`;
}

// 图表绘制
function drawChart(code, chartData) {
  const el = document.getElementById(`chart-${code}`);
  if (!el) return;
  if (el.clientWidth === 0 || el.clientHeight === 0) {
    setTimeout(() => drawChart(code, chartData), 100);
    return;
  }
  if (allCharts[code]) {
    allCharts[code].dispose();
  }
  const chart = echarts.init(el);
  allCharts[code] = chart;
  const times = chartData.map(d => d.time);
  const prices = chartData.map(d => d.price);
  const avgs = chartData.map(d => d.avg);
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

// 主加载流程
async function load(){
  const grid = document.getElementById("grid");
  destroyAllCharts();

  // 1. 获取基础行情与分时
  const baseList = await Promise.all(stocks.map(s => fetchBase(s)));
  const minutesList = await Promise.all(stocks.map(s => fetchMinute(s)));
  // 2. 获取主动买卖详情
  const detailsList = await Promise.all(stocks.map(s => fetchDetails(s)));

  // 3. 合并数据并进行个股分析
  const stockDataList = stocks.map((s, i) => {
    const base = baseList[i];
    const chartData = minutesList[i];
    const details = detailsList[i];
    const merged = { ...base, ...details };
    const analysis = analyzeStock(merged, chartData);
    return { ...merged, ...analysis, chartData };
  });

  // 4. 板块统计
  const sector = calcSector(stockDataList);
  document.getElementById("sector-panel").innerHTML = `
    <h2 style="margin:0 0 6px">板块状态：${sector.signal}</h2>
    <div>强势股数量：${sector.strong}</div>
    <div>弱势股数量：${sector.weak}</div>
    <div>站上均线数量：${sector.aboveAvg}</div>
    <div>主动买入占优数量：${sector.activeBuyDom}</div>
  `;

  // 5. 生成卡片并插入网格
  let html = '';
  stockDataList.forEach(stock => {
    html += cardHtml(stock, stock);  // 分析结果已合并到 stock 自身
  });
  grid.innerHTML = html;

  // 6. 绘制图表
  requestAnimationFrame(() => {
    stockDataList.forEach(stock => {
      drawChart(stock.code, stock.chartData);
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
setInterval(load, 30000);
</script>
</body>
</html>
"""

# ============================================================
# 单股详情页模板（保留原版）
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
