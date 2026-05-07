import os
import requests
import json
from flask import Flask, jsonify, render_template_string, request
import pandas as pd
from datetime import datetime

app = Flask(__name__)

def code_to_eastmoney_secid(code):
    """将 sh/sz 代码转换为东方财富 secid，例如 sh600036 -> 1.600036"""
    if code.startswith('sh'):
        digits = code[2:]
        market = '1'
    elif code.startswith('sz'):
        digits = code[2:]
        market = '0'
    else:
        digits = code
        market = '1' if digits.startswith('6') else '0'
    return f"{market}.{digits}"

# ---------- 东方财富实时行情（盘口） ----------
@app.route('/api/quote')
def quote():
    code = request.args.get('code', 'sh600036')
    secid = code_to_eastmoney_secid(code)
    try:
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            'secid': secid,
            'fields': 'f43,f44,f45,f46,f47,f48,f50,f57,f58,f170',
            'invt': '2',
            'fltt': '2'
        }
        headers = {'Referer': 'https://quote.eastmoney.com/'}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        data = resp.json().get('data', {})
        if not data:
            return jsonify({"error": "未获取到数据"}), 404
        return jsonify({
            "name": data.get('f58', ''),
            "price": data.get('f43', 0) / 100 if data.get('f43') else 0,
            "last_close": data.get('f60', 0) / 100 if data.get('f60') else 0,
            "open": data.get('f46', 0) / 100 if data.get('f46') else 0,
            "high": data.get('f44', 0) / 100 if data.get('f44') else 0,
            "low": data.get('f45', 0) / 100 if data.get('f45') else 0,
            "volume": data.get('f47', 0),
            "amount": data.get('f48', 0),
            # 东方财富免费接口一般不提供五档盘口，可留空
            "buy1": "-", "sell1": "-", "bp1": "-", "sp1": "-"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 盘中实时分时（东方财富 1分钟K线，当日） ----------
@app.route('/api/minute_data')
def minute_data():
    code = request.args.get('code', 'sh600036')
    secid = code_to_eastmoney_secid(code)
    try:
        # 用今天的日期
        today = datetime.now().strftime('%Y%m%d')
        url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '1',       # 1分钟
            'fqt': '0',
            'end': today,
            'lmt': '240'
        }
        headers = {'Referer': 'https://quote.eastmoney.com/'}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        result = resp.json()
        if result.get('data') and result['data'].get('klines'):
            lines = result['data']['klines']
            data = []
            for line in lines:
                parts = line.split(',')
                if len(parts) >= 6:
                    time_str = parts[0][-8:]  # 例如 "09:30:00"
                    data.append({
                        "time": time_str[:5],  # "09:30"
                        "price": float(parts[2]),
                        "volume": int(parts[5])
                    })
            trade_date = lines[0].split(',')[0][:10]
            return jsonify({"success": True, "data": data, "source": "东方财富 (当日)"})
        else:
            return jsonify({"error": "暂无盘中分时数据"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 历史分时（同东方财富，可指定日期） ----------
@app.route('/api/hist_minute_data')
def hist_minute_data():
    code = request.args.get('code', 'sh600036')
    date_str = request.args.get('date', datetime.now().strftime('%Y%m%d'))
    secid = code_to_eastmoney_secid(code)
    try:
        url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '1',
            'fqt': '0',
            'end': date_str,
            'lmt': '240'
        }
        headers = {'Referer': 'https://quote.eastmoney.com/'}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        result = resp.json()
        if result.get('data') and result['data'].get('klines'):
            lines = result['data']['klines']
            data = []
            for line in lines:
                parts = line.split(',')
                if len(parts) >= 6:
                    time_str = parts[0][-8:]
                    data.append({
                        "time": time_str[:5],
                        "price": float(parts[2]),
                        "volume": int(parts[5])
                    })
            trade_date = lines[0].split(',')[0][:10]
            return jsonify({"success": True, "data": data, "trade_date": trade_date, "source": "东方财富 (历史)"})
        else:
            return jsonify({"error": "未获取到历史分时数据"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 前端页面（同之前，修改了盘口显示字段） ----------
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

    <div id="timeline" class="tabcontent" style="display: block;">
        <div id="quote-panel">
            <span>最新价: <b id="q_price">--</b></span>
            <span>涨幅: <b id="q_pct">--</b></span>
            <span>成交量: <b id="q_vol">--</b></span>
        </div>
        <div class="sub-tab">
            <button id="btn_realtime" onclick="switchToRealtime()" style="font-weight:bold;">盘中实时</button>
            <button id="btn_history" onclick="switchToHistory()">盘后复盘</button>
            <input type="date" id="dateInput" style="margin-left:10px;">
        </div>
        <div id="chart-container"></div>
        <div id="data_source" style="font-size:12px; color:#888;"></div>
    </div>

    <div id="kline" class="tabcontent">
        <div class="tradingview-widget-container">
            <div id="tradingview_kline"></div>
        </div>
    </div>

    <script>
        let currentCode = window.location.pathname.split('/stock/')[1] || 'sh600036';
        let chart = null;
        let tvWidget = null;
        let activeSubTab = 'realtime';

        window.onload = function() {
            document.getElementById('codeInput').value = currentCode;
            openTab(null, 'timeline');
            loadQuote();
            loadMinuteData();
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

        function loadQuote() {
            fetch('/api/quote?code=' + currentCode)
                .then(r => r.json())
                .then(d => {
                    if (d && !d.error) {
                        document.getElementById('stockTitle').innerText = (d.name || currentCode) + ' (' + currentCode + ')';
                        document.getElementById('q_price').innerText = d.price || '--';
                        let pct = d.last_close ? ((d.price - d.last_close) / d.last_close * 100).toFixed(2) : '--';
                        document.getElementById('q_pct').innerText = pct + '%';
                        document.getElementById('q_vol').innerText = d.volume || '--';
                    }
                }).catch(() => {});
        }

        function loadMinuteData() {
            document.getElementById('data_source').innerText = '加载中...';
            fetch('/api/minute_data?code=' + currentCode)
                .then(r => r.json())
                .then(res => {
                    if (res.success) {
                        drawChart(res.data);
                        document.getElementById('data_source').innerText = '数据来源：东方财富（当日分时）';
                    } else {
                        document.getElementById('chart-container').innerHTML = '<p>暂无盘中分时数据，可切换至“盘后复盘”</p>';
                        document.getElementById('data_source').innerText = '';
                    }
                }).catch(e => {
                    document.getElementById('chart-container').innerHTML = '<p>获取数据失败</p>';
                });
        }

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
                        document.getElementById('data_source').innerText = '数据来源：东方财富（历史回放） - 交易日期：' + res.trade_date;
                    } else {
                        document.getElementById('chart-container').innerHTML = '<p>未获取到历史分时数据</p>';
                        document.getElementById('data_source').innerText = '';
                    }
                }).catch(e => {
                    document.getElementById('chart-container').innerHTML = '<p>获取数据失败</p>';
                });
        }

        function drawChart(data) {
            const times = data.map(d => d.time);
            const prices = data.map(d => d.price);
            const volumes = data.map(d => d.volume);
            if (!chart) chart = echarts.init(document.getElementById('chart-container'));
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

        function openTab(evt, tabName) {
            const tabs = document.getElementsByClassName('tabcontent');
            for (let t of tabs) t.style.display = 'none';
            const links = document.getElementsByClassName('tablinks');
            for (let l of links) l.classList.remove('active');
            document.getElementById(tabName).style.display = 'block';
            if (evt) evt.currentTarget.classList.add('active');
            else document.querySelector('.tablinks').classList.add('active');
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
