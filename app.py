import os
import requests
from flask import Flask, jsonify, render_template_string, request
from mootdx.quotes import Quotes
import pandas as pd
from datetime import datetime

app = Flask(__name__)
# 初始化通达信行情接口（标准市场）
tdx_client = Quotes.factory(market='std')

def code_to_market(code):
    """将 sh/sz 代码转换为通达信的市场参数 0 深 1 沪"""
    if code.startswith('sz') or (code.isdigit() and (code.startswith('0') or code.startswith('3'))):
        return 0, code.replace('sz','').replace('SZ','')
    elif code.startswith('sh') or (code.isdigit() and code.startswith('6')):
        return 1, code.replace('sh','').replace('SH','')
    else:
        # 默认深市
        return 0, code

# 新浪接口保留，用于获取股票名称和简单实时行情（作为盘口显示的后备）
def fetch_stock_from_sina(code):
    url = f"https://hq.sinajs.cn/list={code}"
    headers = {"Referer": "https://finance.sina.com.cn"}
    resp = requests.get(url, headers=headers, timeout=5)
    resp.encoding = "gbk"
    raw = resp.text
    data_str = raw.split('"')[1]
    if not data_str:
        return None
    fields = data_str.split(",")
    return {
        "name": fields[0],
        "price": float(fields[3]),
        "change": round(float(fields[3]) - float(fields[2]), 2),
        "pct": round((float(fields[3]) - float(fields[2])) / float(fields[2]) * 100, 2),
        "high": fields[4],
        "low": fields[5],
        "open": fields[1],
        "pre_close": fields[2],
    }

# ---------- 新增 API：当日分钟级分时数据（mootdx） ----------
@app.route('/api/minute_data')
def minute_data():
    code = request.args.get('code', 'sh000001')
    market, raw_code = code_to_market(code)
    try:
        # 获取当日分钟K线数据，type=0 为5分钟线，这里用1分钟线（通达信 type=3 是1分钟？）
        # 实际上通达信标准接口：get_minute_time 可能返回当日所有分钟数据
        # 这里使用 get_minute_time(symbol, market) 直接返回分时数据
        df = tdx_client.minute(symbol=raw_code, market=market)
        if df is None or df.empty:
            return jsonify({"error": "未获取到分时数据，可能非交易时间"}), 404

        # 数据格式：时间 'time'，价格 'price'，成交量 'volume'
        # 转换为前端需要的格式
        data = []
        for _, row in df.iterrows():
            # 时间格式通常为 '0930' 这样的字符串，需要补全为 '09:30'
            t = str(row.get('time', row.get('分钟', '')))
            if len(t) == 4:
                t = t[:2] + ':' + t[2:]
            data.append({
                "time": t,
                "price": float(row['price']),
                "volume": int(row['volume'])
            })
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 新增 API：五档盘口（mootdx 实时行情） ----------
@app.route('/api/quote')
def quote():
    code = request.args.get('code', 'sh000001')
    market, raw_code = code_to_market(code)
    try:
        # 获取实时盘口
        res = tdx_client.quotes(symbol=raw_code, market=market)
        if res is None or res.empty:
            return jsonify({"error": "获取盘口失败"}), 404
        row = res.iloc[0]
        return jsonify({
            "name": row.get('name', ''),
            "price": float(row['price']),
            "last_close": float(row['last_close']),
            "open": float(row['open']),
            "high": float(row['high']),
            "low": float(row['low']),
            "volume": int(row['volume']),
            "amount": float(row['amount']),
            "buy1": float(row['buy1']),
            "sell1": float(row['sell1']),
            "bp1": int(row['bp1']),
            "sp1": int(row['sp1']),
            # 可扩展更多档位
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 全新前端模板（融合 TradingView K线 + ECharts 分时盘口） ----------
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>股票高级看板</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        #search-box { margin-bottom: 10px; }
        #codeInput { padding: 10px; font-size: 16px; width: 150px; }
        button { padding: 10px 15px; cursor: pointer; }
        .tab { overflow: hidden; border-bottom: 1px solid #ccc; margin-bottom: 10px; }
        .tab button { background-color: #f1f1f1; float: left; border: none; outline: none; cursor: pointer; padding: 10px 20px; }
        .tab button.active { background-color: #ddd; }
        .tabcontent { display: none; padding: 6px 12px; border-top: none; }
        #quote-panel { margin: 10px 0; padding: 10px; border: 1px solid #eee; background: #fafafa; }
        #chart-container { width: 100%; height: 400px; }
    </style>
</head>
<body>
    <div id="search-box">
        <input type="text" id="codeInput" placeholder="输入代码 如600036">
        <button onclick="switchStock()">查询</button>
    </div>
    <h2 id="stockTitle">加载中...</h2>

    <div class="tab">
        <button class="tablinks active" onclick="openTab(event, 'timeline')">分时图（自主）</button>
        <button class="tablinks" onclick="openTab(event, 'kline')">K线图 (TradingView)</button>
    </div>

    <!-- 自主分时图标签页 -->
    <div id="timeline" class="tabcontent" style="display: block;">
        <div id="quote-panel">
            <span>最新价: <b id="q_price">--</b></span>
            <span>涨幅: <b id="q_pct">--</b></span>
            <span>成交量: <b id="q_vol">--</b></span>
            <span>买一: <b id="q_buy1">--</b></span>
            <span>卖一: <b id="q_sell1">--</b></span>
        </div>
        <div id="chart-container"></div>
    </div>

    <!-- TradingView K线图标签页 -->
    <div id="kline" class="tabcontent">
        <div class="tradingview-widget-container">
            <div id="tradingview_kline"></div>
        </div>
    </div>

    <script>
        let currentCode = window.location.pathname.split('/stock/')[1] || 'sh600036';
        let chart = null;
        let tvWidget = null;

        window.onload = function() {
            document.getElementById('codeInput').value = currentCode;
            openTab(null, 'timeline');
            loadAllData();
        };

        function switchStock() {
            let input = document.getElementById('codeInput').value.trim();
            if (!input) return;
            if (/^\d{6}$/.test(input)) input = (input.startsWith('6') ? 'sh' : 'sz') + input;
            currentCode = input.toLowerCase();
            window.history.pushState(null, null, '/stock/' + currentCode);
            loadAllData();
        }

        async function loadAllData() {
            document.getElementById('stockTitle').innerText = currentCode;
            // 加载盘口
            fetch('/api/quote?code=' + currentCode)
                .then(r => r.json())
                .then(d => {
                    if (d && d.name) {
                        document.getElementById('stockTitle').innerText = d.name + ' (' + currentCode + ')';
                        document.getElementById('q_price').innerText = d.price;
                        let pct = ((d.price - d.last_close) / d.last_close * 100).toFixed(2);
                        document.getElementById('q_pct').innerText = pct + '%';
                        document.getElementById('q_vol').innerText = d.volume;
                        document.getElementById('q_buy1').innerText = d.buy1 + '(' + d.bp1 + ')';
                        document.getElementById('q_sell1').innerText = d.sell1 + '(' + d.sp1 + ')';
                    }
                });
            // 加载分时图
            fetch('/api/minute_data?code=' + currentCode)
                .then(r => r.json())
                .then(res => {
                    if (res.success) {
                        drawMinuteChart(res.data);
                    } else {
                        document.getElementById('chart-container').innerHTML = '<p>暂无分时数据（可能非交易时间）</p>';
                    }
                });
            // 加载/更新 TradingView K线图（只在切换到K线标签时初始化）
        }

        function drawMinuteChart(data) {
            const times = data.map(d => d.time);
            const prices = data.map(d => d.price);
            const volumes = data.map(d => d.volume);

            if (!chart) {
                chart = echarts.init(document.getElementById('chart-container'));
            }
            chart.setOption({
                tooltip: { trigger: 'axis' },
                grid: [
                    { left: '8%', right: '8%', top: '10%', height: '50%' },
                    { left: '8%', right: '8%', top: '65%', height: '25%' }
                ],
                xAxis: [
                    { type: 'category', data: times, gridIndex: 0, axisLabel: { rotate: 30 } },
                    { type: 'category', data: times, gridIndex: 1, axisLabel: { show: false } }
                ],
                yAxis: [
                    { type: 'value', gridIndex: 0, scale: true },
                    { type: 'value', gridIndex: 1, scale: true }
                ],
                series: [
                    { name: '价格', type: 'line', data: prices, smooth: true, symbol: 'none', xAxisIndex: 0, yAxisIndex: 0 },
                    { name: '成交量', type: 'bar', data: volumes, xAxisIndex: 1, yAxisIndex: 1 }
                ]
            });
        }

        function openTab(evt, tabName) {
            const tabs = document.getElementsByClassName('tabcontent');
            for (let t of tabs) t.style.display = 'none';
            const links = document.getElementsByClassName('tablinks');
            for (let l of links) l.classList.remove('active');
            document.getElementById(tabName).style.display = 'block';
            if (evt) evt.currentTarget.classList.add('active');
            else document.querySelector('.tablinks').classList.add('active');

            // 切换到 K 线时，懒加载 TradingView 组件
            if (tabName === 'kline' && !tvWidget) {
                let symbol = currentCode.replace('sh','SSE:').replace('sz','SZSE:');
                tvWidget = new TradingView.widget({
                    "container_id": "tradingview_kline",
                    "autosize": true,
                    "symbol": symbol,
                    "interval": "D",
                    "timezone": "Asia/Shanghai",
                    "theme": "light",
                    "style": "1",
                    "locale": "zh_CN",
                    "toolbar_bg": "#f1f3f6",
                    "enable_publishing": false,
                    "hide_side_toolbar": false,
                    "allow_symbol_change": false,
                    "details": true,
                    "width": "100%",
                    "height": 600
                });
            }
        }
    </script>
</body>
</html>"""

# ---------- 路由 ----------
@app.route("/")
@app.route("/stock/<code>")
def index(code=None):
    return render_template_string(HTML_TEMPLATE, code=code)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
