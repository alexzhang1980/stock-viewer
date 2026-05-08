import os
import requests
from flask import Flask, jsonify, render_template_string
from datetime import datetime

app = Flask(__name__)

# =========================================================
# 股票列表
# =========================================================

stocks = [
    {"name": "中芯国际", "code": "688981", "secid": "1.688981"},
    {"name": "兆易创新", "code": "603986", "secid": "1.603986"},
    {"name": "寒武纪", "code": "688256", "secid": "1.688256"},
    {"name": "北方华创", "code": "002371", "secid": "0.002371"},
    {"name": "海光信息", "code": "688041", "secid": "1.688041"},
    {"name": "豪威集团", "code": "603501", "secid": "1.603501"},
]

# =========================================================
# HTML
# =========================================================

HTML = r"""
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>半导体六股联动监控台</title>

<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>

<style>

body{
    margin:0;
    background:#f3f4f6;
    font-family:Arial,"Microsoft YaHei";
}

header{
    background:#111827;
    color:white;
    padding:14px 20px;
}

header h1{
    margin:0;
    font-size:22px;
}

#time{
    margin-top:5px;
    font-size:13px;
    color:#cbd5e1;
}

#sector{
    margin:12px;
    padding:14px;
    background:white;
    border-radius:12px;
    box-shadow:0 2px 8px rgba(0,0,0,.08);
    line-height:1.9;
}

.grid{
    display:grid;
    grid-template-columns:repeat(3,1fr);
    gap:12px;
    padding:12px;
}

.card{
    background:white;
    border-radius:12px;
    padding:12px;
    box-shadow:0 2px 8px rgba(0,0,0,.08);
}

.name{
    font-size:20px;
    font-weight:bold;
}

.code{
    color:#6b7280;
    font-size:13px;
}

.price{
    font-size:32px;
    font-weight:bold;
    margin-top:6px;
}

.chart{
    width:100%;
    height:180px;
    margin-top:10px;
}

.info{
    margin-top:8px;
    line-height:1.9;
    font-size:13px;
}

.decision{
    margin-top:10px;
    background:#f9fafb;
    border-radius:10px;
    padding:10px;
    line-height:1.8;
    font-size:13px;
}

.red{
    color:#dc2626;
}

.green{
    color:#16a34a;
}

.orange{
    color:#ea580c;
}

.gray{
    color:#6b7280;
}

footer{
    padding:14px;
    font-size:13px;
    color:#6b7280;
}

@media(max-width:1000px){
    .grid{
        grid-template-columns:repeat(2,1fr);
    }
}

@media(max-width:650px){
    .grid{
        grid-template-columns:1fr;
    }
}

</style>
</head>
<body>

<header>
    <h1>半导体六股联动监控台</h1>
    <div id="time">加载中...</div>
</header>

<div id="sector">加载中...</div>

<div class="grid" id="grid"></div>

<footer>
自动刷新：30秒一次。  
评分高于5分才考虑重点观察。  
低于0分原则上不参与。
</footer>

<script>

const stocks = {{ stocks|safe }};

let charts = {};

function formatMoney(v){

    if(v === undefined || v === null) return "--";

    const abs = Math.abs(v);

    if(abs >= 100000000){
        return (v / 100000000).toFixed(2) + "亿";
    }

    if(abs >= 10000){
        return (v / 10000).toFixed(2) + "万";
    }

    return v.toFixed(0);
}

function getColor(v){

    if(v > 0) return "#dc2626";

    if(v < 0) return "#16a34a";

    return "#333";
}

async function getJson(url){

    const r = await fetch(url + "&_=" + Date.now(), {
        cache:"no-store"
    });

    return await r.json();
}

async function fetchBase(stock){

    const url =
    `https://push2.eastmoney.com/api/qt/stock/get?secid=${stock.secid}&fields=f43,f44,f45,f46,f47,f48,f57,f58,f60,f170`;

    const j = await getJson(url);

    const d = j.data || {};

    return {

        ...stock,

        price: d.f43 ? d.f43 / 100 : 0,

        high: d.f44 ? d.f44 / 100 : 0,

        low: d.f45 ? d.f45 / 100 : 0,

        open: d.f46 ? d.f46 / 100 : 0,

        amount: d.f48 || 0,

        yesterday: d.f60 ? d.f60 / 100 : 0,

        changePercent: d.f170 ? d.f170 / 100 : 0
    };
}

async function fetchMinute(stock){

    const url =
    `https://push2his.eastmoney.com/api/qt/stock/trends2/get?secid=${stock.secid}&fields1=f1,f2,f3,f4,f5,f6,f7,f8&fields2=f51,f52,f53,f54,f55,f56,f57,f58`;

    const j = await getJson(url);

    const arr = j.data?.trends || [];

    return arr.map(x=>{

        const a = x.split(",");

        return {

            time:a[0]?.slice(11,16),

            price:Number(a[2]),

            avg:Number(a[7]),

            volume:Number(a[5]),

            amount:Number(a[6])

        };

    }).filter(x=>x.price > 0);
}

async function fetchDetails(stock){

    const url =
    `https://push2.eastmoney.com/api/qt/stock/details/get?secid=${stock.secid}&fields1=f1,f2,f3,f4&fields2=f51,f52,f53,f54,f55`;

    const j = await getJson(url);

    const details = j.data?.details || [];

    if(!Array.isArray(details)){

        return {

            activeBuy:0,
            activeSell:0,
            buySellDiff:0,

            bigBuy:0,
            bigSell:0,
            bigOrderDiff:0
        };
    }

    let activeBuy = 0;
    let activeSell = 0;

    let bigBuy = 0;
    let bigSell = 0;

    details.forEach(item=>{

        const a = item.split(",");

        if(a.length < 5) return;

        const price = Number(a[1]);

        const volume = Number(a[2]);

        const direction = String(a[4]).trim();

        const money = price * volume * 100;

        if(!price || !volume || money <= 0) return;

        // 主动买

        if(direction === "2"){

            activeBuy += money;

            if(money >= 500000){

                bigBuy += money;
            }
        }

        // 主动卖

        else if(direction === "1"){

            activeSell += money;

            if(money >= 500000){

                bigSell += money;
            }
        }

    });

    return {

        activeBuy,
        activeSell,

        buySellDiff: activeBuy - activeSell,

        bigBuy,
        bigSell,

        bigOrderDiff: bigBuy - bigSell
    };
}

function analyze(stock, minute){

    let score = 0;

    let trend = "震荡观察";

    let action = "继续等待";

    let risk = "中性";

    const latest = minute[minute.length - 1];

    const avg = latest?.avg || 0;

    if(stock.changePercent > 1) score += 2;

    if(stock.changePercent > 3) score += 2;

    if(stock.changePercent < -2) score -= 2;

    if(stock.changePercent < -4) score -= 2;

    if(stock.price > avg && avg > 0) score += 2;

    if(stock.price < avg && avg > 0) score -= 2;

    if(stock.buySellDiff > 0) score += 2;

    if(stock.buySellDiff < 0) score -= 2;

    if(stock.bigOrderDiff > 0) score += 2;

    if(stock.bigOrderDiff < 0) score -= 2;

    if(score >= 5){

        trend = "强势";

        action = "重点观察";

        risk = "偏低";
    }

    else if(score >= 2){

        trend = "转强观察";

        action = "等待确认";

        risk = "中性";
    }

    else if(score <= -4){

        trend = "弱势回避";

        action = "不买，继续等";

        risk = "偏高";
    }

    return {

        score,
        trend,
        action,
        risk,
        avg
    };
}

function drawChart(code,data){

    const el = document.getElementById("chart-" + code);

    if(!el) return;

    if(charts[code]){

        charts[code].dispose();
    }

    const chart = echarts.init(el);

    charts[code] = chart;

    chart.setOption({

        animation:false,

        grid:{
            left:8,
            right:8,
            top:10,
            bottom:10
        },

        tooltip:{
            trigger:"axis"
        },

        xAxis:{
            type:"category",
            show:false,
            data:data.map(x=>x.time)
        },

        yAxis:{
            type:"value",
            show:false,
            scale:true
        },

        series:[

            {
                type:"line",
                smooth:true,
                showSymbol:false,
                data:data.map(x=>x.price),
                lineStyle:{
                    width:1.5
                },
                areaStyle:{
                    opacity:0.12
                }
            },

            {
                type:"line",
                smooth:true,
                showSymbol:false,
                data:data.map(x=>x.avg),
                lineStyle:{
                    width:1,
                    type:"dashed"
                }
            }

        ]
    });
}

function sectorInfo(arr){

    const strong = arr.filter(x=>x.score >= 5).length;

    const weak = arr.filter(x=>x.score <= -4).length;

    const above = arr.filter(x=>x.price > x.avg).length;

    const active = arr.filter(x=>x.buySellDiff > 0).length;

    let signal = "板块震荡观察";

    if(strong >= 3){

        signal = "板块转强";
    }

    if(weak >= 4){

        signal = "板块整体偏弱";
    }

    return {

        signal,
        strong,
        weak,
        above,
        active
    };
}

function card(stock){

    const color = getColor(stock.changePercent);

    return `

    <div class="card">

        <div class="name">${stock.name}</div>

        <div class="code">${stock.code}</div>

        <div class="price" style="color:${color}">
            ${stock.price.toFixed(2)}
        </div>

        <div style="color:${color}">
            涨幅：${stock.changePercent.toFixed(2)}%
        </div>

        <div class="chart" id="chart-${stock.code}"></div>

        <div class="info">

            <div>今开：${stock.open.toFixed(2)}</div>

            <div>最高：${stock.high.toFixed(2)}</div>

            <div>最低：${stock.low.toFixed(2)}</div>

            <div>昨收：${stock.yesterday.toFixed(2)}</div>

            <div>成交额：${formatMoney(stock.amount)}</div>

            <div>均价：${stock.avg.toFixed(2)}</div>

        </div>

        <div class="decision">

            <div>评分：${stock.score}</div>

            <div>
            操作提示：
            <span style="font-weight:bold;color:${color}">
            ${stock.action}
            </span>
            </div>

            <div>风险：${stock.risk}</div>

            <div>分时趋势：${stock.trend}</div>

            <div style="color:${getColor(stock.buySellDiff)}">
            主动买卖差：${formatMoney(stock.buySellDiff)}
            </div>

            <div style="color:${getColor(stock.bigOrderDiff)}">
            大单净额：${formatMoney(stock.bigOrderDiff)}
            </div>

            <div>
            主动买：${formatMoney(stock.activeBuy)}
            /
            主动卖：${formatMoney(stock.activeSell)}
            </div>

            <div>
            大单买：${formatMoney(stock.bigBuy)}
            /
            大单卖：${formatMoney(stock.bigSell)}
            </div>

        </div>

    </div>
    `;
}

async function load(){

    const grid = document.getElementById("grid");

    const baseList =
    await Promise.all(stocks.map(fetchBase));

    const minuteList =
    await Promise.all(stocks.map(fetchMinute));

    const detailList =
    await Promise.all(stocks.map(fetchDetails));

    const result = stocks.map((s,i)=>{

        const merged = {

            ...baseList[i],

            ...detailList[i]
        };

        const analysis =
        analyze(merged,minuteList[i]);

        return {

            ...merged,

            ...analysis,

            minute:minuteList[i]
        };
    });

    const sector = sectorInfo(result);

    document.getElementById("sector").innerHTML = `

        <h2 style="margin:0 0 8px">
        板块状态：${sector.signal}
        </h2>

        <div>强势股数量：${sector.strong}</div>

        <div>弱势股数量：${sector.weak}</div>

        <div>站上均线数量：${sector.above}</div>

        <div>主动买入占优数量：${sector.active}</div>
    `;

    grid.innerHTML =
    result.map(card).join("");

    requestAnimationFrame(()=>{

        result.forEach(x=>{

            drawChart(x.code,x.minute);
        });
    });

    document.getElementById("time").innerText =
    "最后刷新：" + new Date().toLocaleTimeString();
}

window.addEventListener("resize",()=>{

    Object.values(charts).forEach(c=>{

        c.resize();
    });
});

load();

setInterval(load,30000);

</script>

</body>
</html>
"""

# =========================================================
# ROUTE
# =========================================================

@app.route("/")
def index():
    return render_template_string(
        HTML,
        stocks=stocks
    )

# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port
    )
