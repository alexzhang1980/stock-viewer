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

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>股票实时行情</title>
<style>body{font-family:Arial;max-width:600px;margin:50px auto}
.box{display:flex;gap:10px;margin-bottom:30px}
input{padding:10px;flex:1;font-size:16px}
button{padding:10px 20px;cursor:pointer}
.card{border:1px solid #ddd;border-radius:12px;padding:20px}
.price{font-size:32px;font-weight:bold}.red{color:#e74c3c}.green{color:#2ecc71}</style></head>
<body><h2>📈 股票行情查询</h2>
<div class="box"><input id="c" placeholder="sh600036 或 sz000001" value="{{ code or '' }}"><button onclick="s()">查询</button></div>
<div id="r">{% if stock %}
<div class="card"><h3>{{ stock.name }} ({{ code }})</h3>
<div class="price {{ 'red' if stock.change>0 else 'green' }}">{{ stock.price }}</div>
<p>涨跌：{{ stock.change }} &nbsp; 幅度：{{ stock.pct }}%</p>
<p>今开{{ stock.open }} 高{{ stock.high }} 低{{ stock.low }} 昨收{{ stock.pre_close }}</p></div>
{% else %}<p>输入代码查行情，也可直接访问 /stock/sh600036</p>{% endif %}</div>
<script>function s(){let c=document.getElementById('c').value.trim();if(!c)return;
c=c.toLowerCase();if(/^\d{6}$/.test(c))c=(c.startsWith('6')?'sh':'sz')+c;
window.location.href='/stock/'+c}
document.getElementById('c').addEventListener('keypress',e=>{if(e.key==='Enter')s()})</script></body></html>"""

@app.route("/api/stock/<code>")
def api_stock(code):
    data = fetch_stock_from_sina(code)
    return jsonify({"success":True,"data":data}) if data else jsonify({"success":False}),404

@app.route("/")
@app.route("/stock/<code>")
def index(code=None):
    stock = fetch_stock_from_sina(code) if code else None
    return render_template_string(HTML_TEMPLATE, code=code, stock=stock)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
