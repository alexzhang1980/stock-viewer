import os
import requests
from flask import Flask, jsonify, render_template_string, request
from mootdx.quotes import Quotes
import akshare as ak
import pandas as pd
from datetime import datetime

app = Flask(__name__)
# 初始化通达信行情接口（用于盘中实时分时数据）
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

# ---------- 盘中实时分时（MOOTDX） ----------
@app.route('/api/minute_data')
def minute_data():
    code = request.args.get('code', 'sh600036')
    market, raw_code = code_to_market(code)
    try:
        # 盘中实时分钟数据
        df = tdx_client.minute(symbol=raw_code, market=market)
        if df is None or df.empty:
            return jsonify({"error": "盘中暂无分时数据，可能非交易时间"}), 404
        data = []
        for _, row in df.iterrows():
            t = str(row.get('time', row.get('分钟', '')))
            if len(t) == 4:
                t = t[:2] + ':' + t[2:]
            data.append({
                "time": t,
                "price": float(row['price']),
                "volume": int(row['volume'])
            })
        return jsonify({"success": True, "data": data, "source": "MOOTDX (盘中实时)"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 盘后历史分时（AKShare） ----------
@app.route('/api/hist_minute_data')
def hist_minute_data():
    code = request.args.get('code', 'sh600036')
    # 日期参数前端可传，但AKShare这个接口只返回最近一个交易日的数据，这里保留以便将来扩展
    date_str = request.args.get('date', datetime.now().strftime('%Y%m%d'))
    try:
        # period='1' 表示1分钟线
        df = ak.stock_zh_a_minute(symbol=code, period='1', adjust='')
        if df is None or df.empty:
            return jsonify({"error": "未获取到历史分时数据"}), 404
        data = []
        for _, row in df.iterrows():
            # 时间列可能为 '09:30:00' 格式，取前5位
            t = str(row['时间'])[:5]
            data.append({
                "time": t,
                "price": float(row['收盘']),
                "volume": int(row['成交量'])
            })
        trade_date = str(df.iloc[0]['时间'])[:10]
        return jsonify({"success": True, "data": data, "trade_date": trade_date, "source": "AKShare (历史复盘)"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 五档盘口（MOOTDX） ----------
@app.route('/api/quote')
def quote():
    code = request.args.get('code', 'sh600036')
    market, raw_code = code_to_market(code)
    try:
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
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 前端页面（整合实时 + 历史复盘 + K线） ----------
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
        .sub-tab { margin: 5px 0; }
        .sub-tab button { padding: 6px 12px; font-size: 14px; }
    </style>
</head>
<body>
    <div id="search-box">
        <input type="text" id="codeInput" placeholder="输入代码 如600036">
        <button onclick="switchStock()">查询</button>
    </div>
    <h2 id="stockTitle">加载中...</h2>

    <div class="tab">
        <button class="tablinks active" onclick="openTab(event, 'timeline')">分时图</button>
        <button class="tablinks" onclick="openTab(event, 'kline')">K线图 (TradingView)</button>
    </div>

    <!-- 分时图标签页 -->
    <div id="timeline" class="tabcontent" style="display: block;">
        <div id="quote-panel">
            <span>最新价: <b id="q_price">--</b></span>
            <span>涨幅: <b id="q_pct">--</b></span>
            <span>成交量: <b id="q_vol">--</b></span>
            <span>买一: <b id="q_buy1">--</b></span>
            <span>卖一: <b id="q_sell1">--</b></span>
        </div>

        <!-- 子标签：切换实时 / 历史 -->
        <div class="sub-tab">
            <button id="btn_realtime" onclick="switchToRealtime()" style="font-weight:bold;">盘中实时</button>
            <button id="btn_history" onclick="switchToHistory()">盘后复盘</button>
            <input type="date" id="dateInput" style="margin-left:10px;">
        </div>

        <div id="chart-container"></div>
        <div id="data_source" style="font-size:12px; color:#888;"></div>
    </div>

    <!-- K线图标签页 -->
    <div id="kline" class="tabcontent">
        <div class="tradingview-widget-container">
            <div id="tradingview_kline"></div>
        </div>
    </div>

    <script>
        let currentCode = window.location.pathname.split('/stock/')[1] || 'sh600036';
        let chart = null;
        let tvWidget = null;
        let activeSubTab = 'realtime'; // 'realtime' 或 'history'

        window.onload = function() {
            document.getElementById('codeInput').value = currentCode;
            openTab(null, 'timeline');
            loadQuote();
            loadMinuteData(); // 默认加载实时数据
        };

        function switchStock() {
            let input = document.getElementById('codeInput').value.trim();
            if (!input) return;
            if (/^\d{6}$/.test(input)) input = (input.startsWith('6') ? 'sh' : 'sz') + input;
            currentCode = input.toLowerCase();
            window.history.pushState(null, null, '/stock/' + currentCode);
            document.getElementById('stockTitle').innerText = currentCode;
            loadQuote();
            if (activeSubTab === 'realtime') loadMinuteData();
            else loadHistData();
        }

        // 加载盘口数据
        function loadQuote() {
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
                })
                .catch(() => {});
        }

        // 盘中实时数据
        function loadMinuteData() {
            document.getElementById('data_source').innerText = '加载中...';
            fetch('/api/minute_data?code=' + currentCode)
                .then(r => r.json())
                .then(res => {
                    if (res.success) {
                        drawChart(res.data);
                        document.getElementById('data_source').innerText = '数据来源：MOOTDX（盘中实时）';
                    } else {
                        document.getElementById('chart-container').innerHTML = '<p>暂无盘中分时数据（可能非交易时间），可切换至“盘后复盘”查看历史数据</p>';
                        document.getElementById('data_source').innerText = '';
                    }
                })
                .catch(e => {
                    document.getElementById('chart-container').innerHTML = '<p>获取数据失败</p>';
                });
        }

        // 盘后历史数据
        function loadHistData() {
            let date = document.getElementById('dateInput').value;
            let url = '/api/hist_minute_data?code=' + currentCode;
            if (date) url += '&date=' + date.replace(/-/g, '');
            document.getElementById('data_source').innerText = '加载中...';
            fetch(url)
                .then(r => r.json())
                .then(res => {
                    if (res.success) {
                        drawChart(res.data);
                        document.getElementById('data_source').innerText = '数据来源：AKShare（历史回放） - 交易日期：' + res.trade_date;
                    } else {
                        document.getElementById('chart-container').innerHTML = '<p>未获取到历史分时数据</p>';
                        document.getElementById('data_source').innerText = '';
                    }
                })
                .catch(e => {
                    document.getElementById('chart-container').innerHTML = '<p>获取数据失败</p>';
                });
        }

        // ECharts 绘图
        function drawChart(data) {
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

        function switchToRealtime() {
            activeSubTab = 'realtime';
            document.getElementById('btn_realtime').style.fontWeight = 'bold';
            document.getElementById('btn_history').style.fontWeight = 'normal';
            loadMinuteData();
        }

        function switchToHistory() {
            activeSubTab = 'history';
            document.getElementById('btn_realtime').style.fontWeight = 'normal';
            document.getElementById('btn_history').style.fontWeight = 'bold';
            loadHistData();
        }

        // 主标签切换
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
