import os
import requests
from flask import Flask, jsonify, render_template_string, request
import pandas as pd
from datetime import datetime
import akshare as ak

app = Flask(__name__)

# ---------- 工具函数 ----------
def code_to_eastmoney_secid(code):
    code = code.lower()
    if code.startswith('sh'):
        return f"1.{code[2:]}"
    elif code.startswith('sz'):
        return f"0.{code[2:]}"
    else:
        market = '1' if code.startswith('6') else '0'
        return f"{market}.{code}"

# ---------- 目标股池 ----------
STOCK_LIST = ['sh688981', 'sz002371', 'sh603501', 'sh688041', 'sh688256', 'sh603986']

# ---------- 批量实时行情 ----------
@app.route('/api/batch_quote')
def batch_quote():
    codes = request.args.get('codes', ','.join(STOCK_LIST)).split(',')
    result = {}
    for code in codes:
        secid = code_to_eastmoney_secid(code)
        try:
            url = "https://push2.eastmoney.com/api/qt/stock/get"
            params = {
                'secid': secid,
                'fields': 'f43,f44,f45,f46,f47,f48,f50,f57,f58,f60,f169,f170',
                'invt': '2',
                'fltt': '2'
            }
            h = {'Referer': 'https://quote.eastmoney.com/'}
            r = requests.get(url, params=params, headers=h, timeout=5)
            d = r.json().get('data', {})
            if d:
                result[code] = {
                    "name": d.get('f58', ''),
                    "price": d.get('f43', 0) / 100 if d.get('f43') else 0,
                    "last_close": d.get('f60', 0) / 100 if d.get('f60') else 0,
                    "volume": d.get('f47', 0),
                    "amount": d.get('f48', 0),
                    "volume_ratio": d.get('f50', 0) / 100 if d.get('f50') else 0,
                }
            else:
                result[code] = {"error": "no data"}
        except Exception as e:
            result[code] = {"error": str(e)}
    return jsonify(result)

# ---------- 全量盘口信息 ----------
@app.route('/api/quote/<code>')
def quote_detail(code):
    secid = code_to_eastmoney_secid(code)
    try:
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        # 聚合常用字段 + 五档盘口 (买一至买五/卖一至卖五)
        fields = ('f43,f44,f45,f46,f47,f48,f50,f57,f58,f60,f169,f170,'
                  'f19,f20,f21,f22,f23,f24,f25,f26,f27,f28,f29,f30,f31,f32,f33,f34,f35,f36,f37')
        params = {'secid': secid, 'fields': fields, 'invt': '2', 'fltt': '2'}
        h = {'Referer': 'https://quote.eastmoney.com/'}
        r = requests.get(url, params=params, headers=h, timeout=5)
        d = r.json().get('data', {})
        if not d:
            return jsonify({"error": "no data"}), 404

        # 辅助解析价格(÷100) / 成交量(手)
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
            "price": d.get('f43', 0) / 100 if d.get('f43') else 0,
            "last_close": d.get('f60', 0) / 100 if d.get('f60') else 0,
            "volume": d.get('f47', 0),
            "amount": d.get('f48', 0),
            "volume_ratio": d.get('f50', 0) / 100 if d.get('f50') else 0,
            "buy5": buy5,
            "sell5": sell5
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 分钟K线 ----------
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

# ---------- 分时成交明细（增强版） ----------
@app.route('/api/tick_data/<code>')
def tick_data(code):
    symbol = code.replace('.', '').replace('SZ', 'sz').replace('SH', 'sh')
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

# ---------- 资金强度统计 ----------
@app.route('/api/adv_stats/<code>')
def adv_stats(code):
    symbol = code.replace('.', '').replace('SZ', 'sz').replace('SH', 'sh')
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
# 仪表盘模板
# ============================================================
HTML_DASHBOARD = r"""
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>板块联动仪表盘</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <style>
        body { font-family: Arial; margin: 20px; background: #f5f5f5; }
        .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; }
        .card { background: #fff; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); padding: 12px; min-height: 180px; }
        .card h3 { margin:0 0 8px; font-size: 16px; }
        .metrics { display:flex; justify-content: space-between; font-size: 14px; }
        .up { color: #e74c3c; } .down { color: #2ecc71; }
        .sparkline { width:100%; height:60px; }
        .leader-badge { font-size:12px; padding:2px 6px; border-radius:4px; margin-left:6px; color:#fff; }
        .badge-strong { background:#e67e22; } .badge-resistant { background:#3498db; } .badge-volume { background:#9b59b6; }
    </style>
</head>
<body>
    <h2>🔍 半导体龙头联动监控</h2>
    <div class="grid" id="stockGrid"></div>

    <script>
        const CODES = ['sh688981','sz002371','sh603501','sh688041','sh688256','sh603986'];
        async function loadDashboard() {
            const resp = await fetch('/api/batch_quote?codes='+CODES.join(','));
            const quotes = await resp.json();
            let stats = CODES.map(c => ({code:c, ...quotes[c]})).filter(q => q.price);
            const maxChg = Math.max(...stats.map(s => (s.price-s.last_close)/s.last_close));
            const minChg = Math.min(...stats.map(s => (s.price-s.last_close)/s.last_close));
            const maxVratio = Math.max(...stats.map(s => s.volume_ratio||0));
            const minVratio = Math.min(...stats.map(s => s.volume_ratio||100));
            stats.forEach(s => {
                const chg = (s.price-s.last_close)/s.last_close;
                s.isStrongest = chg === maxChg && maxChg > 0;
                s.isResistant = chg === minChg && minChg < 0;
                s.isVolumeUp = s.volume_ratio === maxVratio;
                s.isVolumeDown = s.volume_ratio === minVratio && minVratio < 0.8;
            });
            const grid = document.getElementById('stockGrid');
            grid.innerHTML = '';
            for (let s of stats) {
                const card = document.createElement('div');
                card.className = 'card';
                card.onclick = () => window.open('/stock/'+s.code, '_blank');
                let badge = '';
                if (s.isStrongest) badge = '<span class="leader-badge badge-strong">最强</span>';
                else if (s.isResistant) badge = '<span class="leader-badge badge-resistant">抗跌</span>';
                if (s.isVolumeUp) badge += '<span class="leader-badge badge-volume">放量</span>';
                else if (s.isVolumeDown) badge += '<span class="leader-badge badge-volume">缩量</span>';
                const chgPercent = s.last_close ? ((s.price - s.last_close)/s.last_close*100).toFixed(2) : 0;
                card.innerHTML = `<h3>${s.name || s.code} ${badge}</h3>
                    <div class="metrics"><span>最新</span><span class="${chgPercent>=0?'up':'down'}">${s.price.toFixed(2)}</span></div>
                    <div class="metrics"><span>涨幅</span><span class="${chgPercent>=0?'up':'down'}">${chgPercent}%</span></div>
                    <div class="metrics"><span>量比</span><span>${(s.volume_ratio||0).toFixed(2)}</span></div>
                    <div id="chart_${s.code}" class="sparkline"></div>`;
                grid.appendChild(card);
                loadSparkline(s.code, 'chart_'+s.code);
            }
        }

        async function loadSparkline(code, divId) {
            const resp = await fetch('/api/minute_kline/'+code);
            const json = await resp.json();
            if (json.success && json.data.length>0) {
                const prices = json.data.map(d => d.close);
                const chart = echarts.init(document.getElementById(divId));
                chart.setOption({
                    grid: { left:0,right:0,top:0,bottom:0 },
                    xAxis: {show:false, data: json.data.map(d=>d.time)},
                    yAxis: {show:false, min: Math.min(...prices)*0.995, max: Math.max(...prices)*1.005},
                    series: [{
                        type: 'line', data: prices, smooth: true, symbol: 'none',
                        lineStyle: {color: '#e74c3c', width:1},
                        areaStyle: {color: 'rgba(231,76,60,0.15)'}
                    }]
                });
                window.addEventListener('resize', () => chart.resize());
            }
        }

        window.onload = loadDashboard;
    </script>
</body>
</html>
"""

# ============================================================
# 单股详情模板
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

# ---------- 路由 ----------
@app.route("/dashboard")
def dashboard():
    return render_template_string(HTML_DASHBOARD)

@app.route("/stock/<code>")
def stock_detail(code):
    return render_template_string(HTML_STOCK_DETAIL)

@app.route("/")
def index():
    return render_template_string(HTML_DASHBOARD)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
