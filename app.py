import os
import requests
import json
import re
from flask import Flask, jsonify, render_template_string, request
from mootdx.quotes import Quotes
import pandas as pd
from datetime import datetime

app = Flask(__name__)
tdx_client = Quotes.factory(market='std')

def code_to_market(code):
    if code.startswith('sz') or (code.isdigit() and (code.startswith('0') or code.startswith('3'))):
        return 0, code.replace('sz','').replace('SZ','')
    elif code.startswith('sh') or (code.isdigit() and code.startswith('6')):
        return 1, code.replace('sh','').replace('SH','')
    else:
        return 0, code

def code_to_eastmoney_secid(code):
    """将 sh/sz 代码转换为东方财富的 secid，例如 sh600036 -> 1.600036"""
    if code.startswith('sh'):
        digits = code[2:]
        market = '1'
    elif code.startswith('sz'):
        digits = code[2:]
        market = '0'
    else:
        # 纯数字
        digits = code
        if digits.startswith('6'):
            market = '1'
        else:
            market = '0'
    return f"{market}.{digits}"

# ---------- 盘中实时分时（MOOTDX） ----------
@app.route('/api/minute_data')
def minute_data():
    code = request.args.get('code', 'sh600036')
    market, raw_code = code_to_market(code)
    try:
        df = tdx_client.minute(symbol=raw_code, market=market)
        if df is None or df.empty:
            return jsonify({"error": "盘中暂无分时数据"}), 404
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

# ---------- 盘后历史分时（东方财富 API） ----------
@app.route('/api/hist_minute_data')
def hist_minute_data():
    code = request.args.get('code', 'sh600036')
    date_str = request.args.get('date', '')  # 格式 YYYYMMDD
    if not date_str:
        date_str = datetime.now().strftime('%Y%m%d')
    secid = code_to_eastmoney_secid(code)
    try:
        # 东方财富 1分钟K线接口
        url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '1',           # 1分钟
            'fqt': '0',           # 不复权
            'end': date_str,      # 目标日期
            'lmt': '240'          # 最大获取240条
        }
        headers = {'Referer': 'https://quote.eastmoney.com/'}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.encoding = 'utf-8'
        result = resp.json()
        if result.get('data') and result['data'].get('klines'):
            lines = result['data']['klines']
            data = []
            for line in lines:
                parts = line.split(',')
                if len(parts) >= 6:
                    # 时间,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
                    time_str = parts[0][-8:]  # 取后8位，如 "09:30:00"
                    data.append({
                        "time": time_str[:5],  # "09:30"
                        "price": float(parts[2]),  # 收盘价作为价格代表
                        "volume": int(parts[5])
                    })
            trade_date = lines[0].split(',')[0][:10]
            return jsonify({"success": True, "data": data, "trade_date": trade_date, "source": "东方财富 (历史复盘)"})
        else:
            return jsonify({"error": "未获取到历史分时数据，可能非交易日或代码有误"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 盘口（MOOTDX） ----------
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

# ---------- 前端页面（同之前，无变化） ----------
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
            <span>买一: <b id="q_buy1">--</b></span>
            <span>卖一: <b id="q_sell1">--</b></span>
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
                    if (d && d.name) {
                        document.getElementById('stockTitle').innerText = d.name + ' (' + currentCode + ')';
                        document.getElementById('q_price').innerText = d.price;
                        let pct = ((d.price - d.last_close) / d.last_close * 100).toFixed(2);
                        document.getElementById('q_pct').innerText = pct + '%';
                        document.getElementById('q_vol').innerText = d.volume;
                        document.getElementById('q_buy1').innerText = d.buy1 + '(' + d.bp1 + ')';
                        document.getElementById('q_sell1').innerText = d.sell1 + '(' + d.sp1 + ')';
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
                        document.getElementById('data_source').innerText = '数据来源：MOOTDX（盘中实时）';
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
