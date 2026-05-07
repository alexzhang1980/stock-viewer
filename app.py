import os
import requests
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

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

# 新的专业模板，嵌入了 TradingView 分时图和 K 线图
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>股票实时看板</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        #search-box { margin-bottom: 10px; }
        #codeInput { padding: 10px; font-size: 16px; width: 150px; }
        button { padding: 10px 15px; cursor: pointer; }
        .tab { overflow: hidden; border-bottom: 1px solid #ccc; margin-bottom: 10px; }
        .tab button { background-color: #f1f1f1; float: left; border: none; outline: none; cursor: pointer; padding: 10px 20px; transition: 0.3s; }
        .tab button.active { background-color: #ddd; }
        .tabcontent { display: none; padding: 6px 12px; border-top: none; }
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
        <button class="tablinks" onclick="openTab(event, 'kline')">K线图</button>
    </div>

    <div id="timeline" class="tabcontent" style="display: block;">
        <div class="tradingview-widget-container">
            <div class="tradingview-widget-container__widget"></div>
        </div>
    </div>

    <div id="kline" class="tabcontent">
        <div class="tradingview-widget-container">
            <div id="tradingview_kline"></div>
        </div>
    </div>

    <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
    <script>
        // 从 URL 中获取当前代码，例如 /stock/sh600036
        let pathCode = window.location.pathname.split('/stock/')[1];
        let currentCode = pathCode || 'sh600036';
        let stockName = '';

        window.onload = function() {
            document.getElementById('codeInput').value = currentCode;
            fetchStockName();
            updateTradingViewWidgets();
        };

        function switchStock() {
            let inputCode = document.getElementById('codeInput').value.trim();
            if (!inputCode) return;
            // 自动补全：纯数字时，6开头加sh，0/3开头加sz
            if (/^\d{6}$/.test(inputCode)) {
                currentCode = (inputCode.startsWith('6') ? 'sh' : 'sz') + inputCode;
            } else {
                currentCode = inputCode.toLowerCase();
            }
            // 更新页面URL，实现可分享链接
            window.history.pushState(null, null, '/stock/' + currentCode);
            fetchStockName();
            updateTradingViewWidgets();
        }

        // 从后端获取股票名称
        function fetchStockName() {
            fetch('/api/stock_info?code=' + currentCode)
                .then(res => res.json())
                .then(data => {
                    if (data.name) {
                        stockName = data.name;
                        document.getElementById('stockTitle').innerText = stockName + ' (' + currentCode + ')';
                    } else {
                        document.getElementById('stockTitle').innerText = currentCode;
                    }
                })
                .catch(() => {
                    document.getElementById('stockTitle').innerText = currentCode;
                });
        }

        function updateTradingViewWidgets() {
            // 将标准代码转换为 TradingView 符号
            // sh600036 -> SSE:600036, sz000001 -> SZSE:000001
            let symbol = currentCode.replace('sh', 'SSE:').replace('sz', 'SZSE:');

            // 清空之前的图表
            document.querySelector('#timeline .tradingview-widget-container__widget').innerHTML = '';
            document.getElementById('tradingview_kline').innerHTML = '';

            // 创建分时图（迷你走势图）
            new TradingView.widget({
                "container_id": "timeline",
                "autosize": true,
                "symbol": symbol,
                "interval": "1",
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
                "height": 500
            });

            // 创建 K 线图
            new TradingView.widget({
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

        function openTab(evt, tabName) {
            var tabcontent = document.getElementsByClassName("tabcontent");
            for (var i = 0; i < tabcontent.length; i++) {
                tabcontent[i].style.display = "none";
            }
            var tablinks = document.getElementsByClassName("tablinks");
            for (var i = 0; i < tablinks.length; i++) {
                tablinks[i].className = tablinks[i].className.replace(" active", "");
            }
            document.getElementById(tabName).style.display = "block";
            evt.currentTarget.className += " active";
        }
    </script>
</body>
</html>"""

@app.route("/api/stock/<code>")
def api_stock(code):
    data = fetch_stock_from_sina(code)
    return jsonify({"success":True,"data":data}) if data else jsonify({"success":False}),404

@app.route("/api/stock_info")
def api_stock_info():
    code = request.args.get('code')
    if not code:
        return jsonify({"error": "missing code"}), 400
    data = fetch_stock_from_sina(code)
    if data:
        return jsonify({"name": data.get("name")})
    else:
        return jsonify({"error": "not found"}), 404

@app.route("/")
@app.route("/stock/<code>")
def index(code=None):
    # 模板中不再依赖股票数据，统一由前端JS调用API获取
    return render_template_string(HTML_TEMPLATE, code=code, stock=None)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
