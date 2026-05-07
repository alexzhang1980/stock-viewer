import os
import requests
from flask import Flask, jsonify, render_template_string, request
import pandas as pd
from datetime import datetime

app = Flask(__name__)

def code_to_eastmoney_secid(code):
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

# ---------- 盘口（已更新，包含量比、内盘、外盘） ----------
@app.route('/api/quote')
def quote():
    code = request.args.get('code', 'sh600036')
    secid = code_to_eastmoney_secid(code)
    try:
        # 东方财富实时行情
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            'secid': secid,
            'fields': 'f43,f44,f45,f46,f47,f48,f50,f57,f58,f60,f169,f170',
            'invt': '2',
            'fltt': '2'
        }
        headers = {'Referer': 'https://quote.eastmoney.com/'}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        data = resp.json().get('data', {})

        if not data:
            return jsonify({"error": "未获取到数据"}), 404

        # 获取内外盘数据（从 AKShare 全市场数据中筛选）
        inner_vol = '--'
        outer_vol = '--'
        net_inflow = '--'
        try:
            import akshare as ak
            df_spot = ak.stock_zh_a_spot_em()
            target_symbol = code.replace('sh', '').replace('sz', '')
            stock_row = df_spot[df_spot['代码'] == target_symbol]
            if not stock_row.empty:
                inner_vol = int(stock_row.iloc[0].get('内盘', 0))
                outer_vol = int(stock_row.iloc[0].get('外盘', 0))
                net_inflow = outer_vol - inner_vol
        except Exception:
            pass  # 获取失败则使用默认值

        return jsonify({
            "name": data.get('f58', ''),
            "price": data.get('f43', 0) / 100 if data.get('f43') else 0,
            "last_close": data.get('f60', 0) / 100 if data.get('f60') else 0,
            "open": data.get('f46', 0) / 100 if data.get('f46') else 0,
            "high": data.get('f44', 0) / 100 if data.get('f44') else 0,
            "low": data.get('f45', 0) / 100 if data.get('f45') else 0,
            "volume": data.get('f47', 0),
            "amount": data.get('f48', 0),
            "volume_ratio": data.get('f50', 0) / 100 if data.get('f50') else 0,  # 量比
            "inner_vol": inner_vol,
            "outer_vol": outer_vol,
            "net_inflow": net_inflow,
            "buy1": "-", "sell1": "-", "bp1": "-", "sp1": "-"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 盘中分时 ----------
@app.route('/api/minute_data')
def minute_data():
    code = request.args.get('code', 'sh600036')
    secid = code_to_eastmoney_secid(code)
    try:
        today = datetime.now().strftime('%Y%m%d')
        url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '1',
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
                    time_str = parts[0][-8:]
                    data.append({
                        "time": time_str[:5],
                        "price": float(parts[2]),
                        "volume": int(parts[5])
                    })
            trade_date = lines[0].split(',')[0][:10]
            return jsonify({"success": True, "data": data, "source": "东方财富 (当日)"})
        else:
            return jsonify({"error": "暂无盘中分时数据"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 历史分时 ----------
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

# ---------- 分时成交明细 ----------
@app.route('/api/tick_data')
def tick_data():
    code = request.args.get('code', 'sh688981')
    symbol = code.replace('.', '').replace('SZ', 'sz').replace('SH', 'sh')
    try:
        import akshare as ak
        df = ak.stock_zh_a_tick_tx_js(symbol=symbol)
        if df is None or df.empty:
            return jsonify({"error": "AKShare returned empty DataFrame", "symbol": symbol})
        data = []
        for _, row in df.iterrows():
            time_val = str(row.get('成交时间', row.get('时间', '')))
            price = row.get('成交价格', row.get('价格', 0))
            volume = row.get('成交量', 0)
            nature = row.get('性质', '')
            direction = 'S'
            if '买' in str(nature):
                direction = 'B'
            data.append({
                '时间': time_val,
                '价格': price,
                '成交': f"{int(volume)} {direction}"
            })
        return jsonify(data)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ---------- 日K线数据（东方财富，120个交易日） ----------
@app.route('/api/daily_kline')
def daily_kline():
    code = request.args.get('code', 'sh600036')
    secid = code_to_eastmoney_secid(code)
    try:
        url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '101',      # 日K线
            'fqt': '1',        # 前复权
            'lmt': '120'       # 120个交易日
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
                    data.append({
                        "date": parts[0],        # 日期
                        "open": float(parts[1]),
                        "close": float(parts[2]),
                        "high": float(parts[3]),
                        "low": float(parts[4]),
                        "volume": int(parts[5])
                    })
            return jsonify({"success": True, "data": data, "source": "东方财富 (日K线)"})
        else:
            return jsonify({"error": "未获取到日K线数据"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 前后端一体页面 ----------
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>股票高级看板</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        #search-box { margin-bottom: 15px; }
        #codeInput { padding: 10px; font-size: 16px; width: 150px; }
        button { padding: 10px 15px; cursor: pointer; }
        h2 { margin: 10px 0; }
        #quote-panel { margin: 10px 0; padding: 12px; border: 1px solid #ddd; background: #f9f9f9; border-radius: 6px; display: flex; flex-wrap: wrap; gap: 12px; align-items: baseline; }
        #quote-panel span { white-space: nowrap; }
        #minute-chart-container { width: 100%; height: 420px; margin-bottom: 30px; border: 1px solid #eee; border-radius: 4px; }
        .sub-tab { margin: 5px 0 15px; }
        .sub-tab button { padding: 6px 12px; font-size: 14px; }
        #tick-table-container { height: 350px; overflow-y: auto; border: 1px solid #ccc; margin: 20px 0 30px; border-radius: 4px; }
        #tick-table { width: 100%; border-collapse: collapse; font-family: monospace; }
        #tick-table th { position: sticky; top: 0; background: #f2f2f2; z-index: 1; }
        #kline-chart-container { width: 100%; height: 520px; margin-top: 30px; margin-bottom: 30px; border: 1px solid #eee; border-radius: 4px; padding: 10px; }
        .section-title { font-size: 18px; font-weight: bold; margin: 25px 0 10px; border-bottom: 2px solid #ccc; padding-bottom: 5px; }
    </style>
</head>
<body>
    <div id="search-box">
        <input type="text" id="codeInput" placeholder="输入代码 如600036">
        <button onclick="switchStock()">查询</button>
    </div>
    <h2 id="stockTitle">加载中...</h2>

    <!-- 盘口数据 -->
    <div id="quote-panel">
        <span>最新价: <b id="q_price">--</b></span>
        <span>涨幅: <b id="q_pct">--</b></span>
        <span>成交量: <b id="q_vol">--</b></span>
        <span>量比: <b id="q_vratio">--</b></span>
        <span>内盘: <b id="q_inner">--</b></span>
        <span>外盘: <b id="q_outer">--</b></span>
        <span>净流入: <b id="q_net">--</b></span>
    </div>

    <!-- 分时图区域 -->
    <div class="section-title">📈 分时走势</div>
    <div class="sub-tab">
        <button id="btn_realtime" onclick="switchToRealtime()" style="font-weight:bold;">盘中实时</button>
        <button id="btn_history" onclick="switchToHistory()">盘后复盘</button>
        <input type="date" id="dateInput" style="margin-left:10px;">
    </div>
    <div id="minute-chart-container"></div>
    <div id="data_source" style="font-size:12px; color:#888;"></div>

    <!-- 分时成交明细 -->
    <div class="section-title">📋 分时成交明细</div>
    <div id="tick-table-container">
        <table id="tick-table">
            <thead>
                <tr>
                    <th style="padding: 8px; border-bottom: 1px solid #ddd;">时间</th>
                    <th style="padding: 8px; border-bottom: 1px solid #ddd;">价格</th>
                    <th style="padding: 8px; border-bottom: 1px solid #ddd;">成交</th>
                </tr>
            </thead>
            <tbody id="tick-table-body"></tbody>
        </table>
    </div>

    <!-- ECharts日K图 -->
    <div class="section-title">📊 日K线图 (东方财富·前复权)</div>
    <div id="kline-chart-container"></div>

    <script>
        let currentCode = window.location.pathname.split('/stock/')[1] || 'sh600036';
        let minuteChart = echarts.init(document.getElementById('minute-chart-container'));
        let klineChart = echarts.init(document.getElementById('kline-chart-container'));
        let activeSubTab = 'realtime';

        window.onload = function() {
            document.getElementById('codeInput').value = currentCode;
            loadQuote();
            loadMinuteData();
            loadTickData(currentCode);
            loadDailyKline();
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
            loadTickData(currentCode);
            loadDailyKline();
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
                        document.getElementById('q_vratio').innerText = d.volume_ratio || '--';
                        document.getElementById('q_inner').innerText = d.inner_vol || '--';
                        document.getElementById('q_outer').innerText = d.outer_vol || '--';
                        document.getElementById('q_net').innerText = d.net_inflow || '--';
                    }
                }).catch(() => {});
        }

        function loadMinuteData() {
            document.getElementById('data_source').innerText = '加载中...';
            fetch('/api/minute_data?code=' + currentCode)
                .then(r => r.json())
                .then(res => {
                    if (res.success) {
                        drawMinuteChart(res.data);
                        document.getElementById('data_source').innerText = '数据来源：东方财富（当日分时）';
                    } else {
                        minuteChart.clear();
                        document.getElementById('data_source').innerText = '暂无盘中分时数据，可切换至“盘后复盘”';
                    }
                }).catch(e => {
                    minuteChart.clear();
                    document.getElementById('data_source').innerText = '获取数据失败';
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
                        drawMinuteChart(res.data);
                        document.getElementById('data_source').innerText = '数据来源：东方财富（历史回放） - 交易日期：' + res.trade_date;
                    } else {
                        minuteChart.clear();
                        document.getElementById('data_source').innerText = '未获取到历史分时数据';
                    }
                }).catch(e => {
                    minuteChart.clear();
                    document.getElementById('data_source').innerText = '获取数据失败';
                });
        }

        function drawMinuteChart(data) {
            const times = data.map(d => d.time);
            const prices = data.map(d => d.price);
            const volumes = data.map(d => d.volume);
            minuteChart.setOption({
                tooltip: { trigger: 'axis' },
                grid: [
                    { left: '10%', right: '8%', top: '10%', height: '50%' },
                    { left: '10%', right: '8%', top: '65%', height: '25%' }
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

        function loadTickData(code) {
            fetch('/api/tick_data?code=' + code)
                .then(r => r.json())
                .then(data => {
                    const tbody = document.getElementById('tick-table-body');
                    tbody.innerHTML = '';
                    data.forEach(row => {
                        const tr = document.createElement('tr');
                        const isBuy = row['成交'].includes('B');
                        tr.style.color = isBuy ? '#e74c3c' : '#2ecc71';
                        tr.innerHTML = `<td style="padding:4px 8px;border-bottom:1px solid #eee;">${row['时间']}</td>
                                        <td style="padding:4px 8px;border-bottom:1px solid #eee;">${row['价格']}</td>
                                        <td style="padding:4px 8px;border-bottom:1px solid #eee;">${row['成交']}</td>`;
                        tbody.appendChild(tr);
                    });
                    const container = document.getElementById('tick-table-container');
                    container.scrollTop = container.scrollHeight;
                }).catch(e => console.error(e));
        }

        // 绘制ECharts日K线图
        function loadDailyKline() {
            fetch('/api/daily_kline?code=' + currentCode)
                .then(r => r.json())
                .then(res => {
                    if (res.success) {
                        const raw = res.data;
                        const dates = raw.map(d => d.date);
                        const ohlc = raw.map(d => [d.open, d.close, d.low, d.high]);
                        const volumes = raw.map(d => d.volume);

                        klineChart.setOption({
                            tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
                            grid: [
                                { left: '10%', right: '8%', top: '10%', height: '55%' },
                                { left: '10%', right: '8%', top: '70%', height: '20%' }
                            ],
                            xAxis: [
                                { type: 'category', data: dates, gridIndex: 0, axisLabel: { rotate: 30 } },
                                { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false } }
                            ],
                            yAxis: [
                                { type: 'value', gridIndex: 0, scale: true, splitArea: { show: true } },
                                { type: 'value', gridIndex: 1, scale: true, axisLabel: { show: false } }
                            ],
                            series: [
                                {
                                    name: 'K线',
                                    type: 'candlestick',
                                    data: ohlc,
                                    xAxisIndex: 0,
                                    yAxisIndex: 0,
                                    itemStyle: {
                                        color: '#e74c3c',
                                        color0: '#2ecc71',
                                        borderColor: '#e74c3c',
                                        borderColor0: '#2ecc71'
                                    }
                                },
                                {
                                    name: '成交量',
                                    type: 'bar',
                                    data: volumes,
                                    xAxisIndex: 1,
                                    yAxisIndex: 1,
                                    itemStyle: {
                                        color: function(params) {
                                            const idx = params.dataIndex;
                                            return raw[idx].close >= raw[idx].open ? '#e74c3c' : '#2ecc71';
                                        }
                                    }
                                }
                            ]
                        });
                    } else {
                        document.getElementById('kline-chart-container').innerHTML = '<p>未获取到日K线数据</p>';
                    }
                }).catch(e => {
                    document.getElementById('kline-chart-container').innerHTML = '<p>获取日K线数据失败</p>';
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

        // 调整图表尺寸
        window.addEventListener('resize', function() {
            minuteChart.resize();
            klineChart.resize();
        });
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
