/**
 * stock-decision-engine.js
 *
 * 用途：
 * 1. 接收股票实时快照数据
 * 2. 自动判断分时强弱、主动买卖、大单连续性、放量情况
 * 3. 输出适合发给 ChatGPT 的盘中简报
 * 4. 给出基础交易提示：观察 / 持有 / 试仓 / 加仓 / 风险
 *
 * 注意：
 * - 这不是自动交易程序。
 * - 它只做辅助判断，不直接下单。
 * - 你需要把自己的行情数据整理成 StockSnapshot 格式传进来。
 */

/**
 * @typedef {Object} TradeTick
 * @property {string} time - 成交时间，例如 "10:31:25"
 * @property {number} price - 成交价
 * @property {number} volume - 成交手数
 * @property {"B"|"S"|"N"} side - B=主动买，S=主动卖，N=中性/未知
 */

/**
 * @typedef {Object} MinutePoint
 * @property {string} time - 分时时间，例如 "10:31"
 * @property {number} price - 当前价
 * @property {number} avgPrice - 分时均价
 * @property {number} volume - 该分钟成交量，单位可自定，但需统一
 */

/**
 * @typedef {Object} StockSnapshot
 * @property {string} code - 股票代码，例如 "002371"
 * @property {string} name - 股票名称，例如 "北方华创"
 * @property {number} currentPrice - 当前价
 * @property {number} avgPrice - 分时均价
 * @property {number} changePercent - 当前涨跌幅，例如 -0.85
 * @property {number} openPrice - 开盘价
 * @property {number} previousClose - 昨收
 * @property {number} highPrice - 日内最高
 * @property {number} lowPrice - 日内最低
 * @property {MinutePoint[]} minuteData - 分时数据
 * @property {TradeTick[]} ticks - 最近逐笔成交，建议至少最近3-10分钟
 */

const BIG_ORDER_THRESHOLD = {
  "688981": 300, // 中芯国际
  "002371": 100, // 北方华创
  "603501": 80,  // 豪威集团
  "688041": 150, // 海光信息，可按实际调整
  "688256": 80,  // 寒武纪，可按实际调整
  "603986": 80,  // 兆易创新，可按实际调整
  default: 100,
};

function getBigOrderThreshold(code) {
  return BIG_ORDER_THRESHOLD[code] || BIG_ORDER_THRESHOLD.default;
}

function safeNumber(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function getRecentItems(arr, count) {
  if (!Array.isArray(arr)) return [];
  return arr.slice(Math.max(0, arr.length - count));
}

function analyzePricePosition(snapshot) {
  const current = safeNumber(snapshot.currentPrice);
  const avg = safeNumber(snapshot.avgPrice);
  const open = safeNumber(snapshot.openPrice);
  const prevClose = safeNumber(snapshot.previousClose);

  const aboveAvg = current > avg;
  const aboveOpen = current > open;
  const abovePrevClose = current > prevClose;

  let level = "中性";
  if (aboveAvg && aboveOpen && abovePrevClose) level = "强势";
  else if (aboveAvg && !abovePrevClose) level = "修复中";
  else if (!aboveAvg && current < open) level = "偏弱";

  return {
    aboveAvg,
    aboveOpen,
    abovePrevClose,
    level,
    text: `当前价${current}，均价${avg}，${aboveAvg ? "站上均价" : "低于均价"}，状态：${level}`,
  };
}

function analyzeMinuteTrend(snapshot) {
  const recent = getRecentItems(snapshot.minuteData, 10);
  if (recent.length < 3) {
    return {
      trend: "数据不足",
      text: "分时数据不足，暂不判断趋势。",
    };
  }

  const first = recent[0].price;
  const last = recent[recent.length - 1].price;
  const avgFirst = recent[0].avgPrice;
  const avgLast = recent[recent.length - 1].avgPrice;

  let aboveAvgCount = 0;
  for (const p of recent) {
    if (p.price >= p.avgPrice) aboveAvgCount += 1;
  }

  const priceChange = last - first;
  const avgChange = avgLast - avgFirst;
  const aboveAvgRatio = aboveAvgCount / recent.length;

  let trend = "横盘震荡";
  if (priceChange > 0 && avgChange >= 0 && aboveAvgRatio >= 0.7) {
    trend = "缓慢抬升";
  } else if (priceChange < 0 && aboveAvgRatio <= 0.4) {
    trend = "震荡下压";
  } else if (aboveAvgRatio >= 0.7) {
    trend = "均价线上方横盘";
  } else if (aboveAvgRatio <= 0.3) {
    trend = "均价线下方弱震荡";
  }

  return {
    trend,
    priceChange,
    avgChange,
    aboveAvgRatio,
    text: `近10分钟分时：${trend}，价格变化${priceChange.toFixed(2)}，均价变化${avgChange.toFixed(2)}。`,
  };
}

function analyzeActiveBuySell(snapshot) {
  const recentTicks = getRecentItems(snapshot.ticks, 80);
  const threshold = getBigOrderThreshold(snapshot.code);

  let buyVolume = 0;
  let sellVolume = 0;
  let neutralVolume = 0;
  let bigBuyCount = 0;
  let bigSellCount = 0;
  let maxConsecutiveBigBuy = 0;
  let maxConsecutiveBigSell = 0;
  let currentBigBuyStreak = 0;
  let currentBigSellStreak = 0;

  for (const tick of recentTicks) {
    const volume = safeNumber(tick.volume);
    if (tick.side === "B") {
      buyVolume += volume;
      if (volume >= threshold) {
        bigBuyCount += 1;
        currentBigBuyStreak += 1;
        currentBigSellStreak = 0;
      } else {
        currentBigBuyStreak = 0;
      }
    } else if (tick.side === "S") {
      sellVolume += volume;
      if (volume >= threshold) {
        bigSellCount += 1;
        currentBigSellStreak += 1;
        currentBigBuyStreak = 0;
      } else {
        currentBigSellStreak = 0;
      }
    } else {
      neutralVolume += volume;
      currentBigBuyStreak = 0;
      currentBigSellStreak = 0;
    }

    maxConsecutiveBigBuy = Math.max(maxConsecutiveBigBuy, currentBigBuyStreak);
    maxConsecutiveBigSell = Math.max(maxConsecutiveBigSell, currentBigSellStreak);
  }

  const total = buyVolume + sellVolume + neutralVolume;
  const buyRatio = total > 0 ? buyVolume / total : 0;
  const sellRatio = total > 0 ? sellVolume / total : 0;

  let strength = "买卖均衡";
  if (buyRatio >= 0.58 && bigBuyCount > bigSellCount) strength = "主动买增强";
  if (sellRatio >= 0.58 && bigSellCount > bigBuyCount) strength = "主动卖增强";
  if (maxConsecutiveBigBuy >= 3) strength = "连续大单主动买";
  if (maxConsecutiveBigSell >= 3) strength = "连续大单主动卖";

  return {
    buyVolume,
    sellVolume,
    neutralVolume,
    buyRatio,
    sellRatio,
    bigBuyCount,
    bigSellCount,
    maxConsecutiveBigBuy,
    maxConsecutiveBigSell,
    strength,
    threshold,
    text: `近80笔：主动买${buyVolume}手，主动卖${sellVolume}手，大单阈值${threshold}手；状态：${strength}。`,
  };
}

function analyzeVolume(snapshot) {
  const recent = getRecentItems(snapshot.minuteData, 10);
  if (recent.length < 6) {
    return {
      status: "数据不足",
      text: "分钟成交量数据不足，暂不判断是否放量。",
    };
  }

  const firstHalf = recent.slice(0, 5);
  const secondHalf = recent.slice(5);
  const avg1 = firstHalf.reduce((sum, p) => sum + safeNumber(p.volume), 0) / firstHalf.length;
  const avg2 = secondHalf.reduce((sum, p) => sum + safeNumber(p.volume), 0) / secondHalf.length;

  const ratio = avg1 > 0 ? avg2 / avg1 : 1;

  let status = "量能平稳";
  if (ratio >= 1.6) status = "明显放量";
  else if (ratio >= 1.25) status = "温和放量";
  else if (ratio <= 0.7) status = "缩量";

  return {
    avgPrevious: avg1,
    avgRecent: avg2,
    ratio,
    status,
    text: `近10分钟量能：${status}，后5分钟/前5分钟量比 ${ratio.toFixed(2)}。`,
  };
}

function generateSignal(snapshot) {
  const price = analyzePricePosition(snapshot);
  const trend = analyzeMinuteTrend(snapshot);
  const active = analyzeActiveBuySell(snapshot);
  const volume = analyzeVolume(snapshot);

  let score = 0;

  if (price.aboveAvg) score += 1;
  if (price.aboveOpen) score += 1;
  if (trend.trend === "缓慢抬升") score += 2;
  if (trend.trend === "均价线上方横盘") score += 1;
  if (active.strength === "主动买增强") score += 2;
  if (active.strength === "连续大单主动买") score += 3;
  if (volume.status === "温和放量") score += 1;
  if (volume.status === "明显放量") score += 2;

  if (trend.trend === "震荡下压") score -= 2;
  if (trend.trend === "均价线下方弱震荡") score -= 1;
  if (active.strength === "主动卖增强") score -= 2;
  if (active.strength === "连续大单主动卖") score -= 3;

  let action = "观察";
  let risk = "中性";

  if (score >= 6) {
    action = "可考虑试仓/持仓";
    risk = "偏强";
  } else if (score >= 3) {
    action = "继续持有观察";
    risk = "中性偏强";
  } else if (score <= -3) {
    action = "风险升高，避免加仓";
    risk = "偏弱";
  } else {
    action = "按兵不动";
    risk = "中性";
  }

  return {
    score,
    action,
    risk,
    price,
    trend,
    active,
    volume,
  };
}

function formatBrief(snapshot) {
  const signal = generateSignal(snapshot);
  const { price, trend, active, volume } = signal;

  return `
${snapshot.name}（${snapshot.code}）

当前价：${snapshot.currentPrice}
均价：${snapshot.avgPrice}
涨跌幅：${snapshot.changePercent}%

分时：
${trend.text}

主动买：
${active.buyVolume}手，${active.strength.includes("买") ? "买盘增强" : "买盘一般"}

主动卖：
${active.sellVolume}手，${active.strength.includes("卖") ? "卖压增强" : "卖压不强"}

是否放量：
${volume.text}

大单情况：
大单阈值：${active.threshold}手
大买单次数：${active.bigBuyCount}
大卖单次数：${active.bigSellCount}
最大连续大买：${active.maxConsecutiveBigBuy}
最大连续大卖：${active.maxConsecutiveBigSell}

系统判断：
评分：${signal.score}
风险状态：${signal.risk}
操作提示：${signal.action}
`.trim();
}

function analyzeStockSnapshot(snapshot) {
  return {
    snapshot,
    signal: generateSignal(snapshot),
    brief: formatBrief(snapshot),
  };
}

function analyzeStockList(snapshots) {
  return snapshots
    .map((snapshot) => analyzeStockSnapshot(snapshot))
    .sort((a, b) => b.signal.score - a.signal.score);
}

// 示例数据：你接入真实行情后，替换这里即可。
const demoSnapshot = {
  code: "002371",
  name: "北方华创",
  currentPrice: 541.8,
  avgPrice: 540.9,
  changePercent: -0.35,
  openPrice: 538.5,
  previousClose: 543.7,
  highPrice: 545.5,
  lowPrice: 536.2,
  minuteData: [
    { time: "10:21", price: 539.2, avgPrice: 540.1, volume: 1200 },
    { time: "10:22", price: 539.8, avgPrice: 540.2, volume: 1280 },
    { time: "10:23", price: 540.2, avgPrice: 540.3, volume: 1350 },
    { time: "10:24", price: 540.8, avgPrice: 540.4, volume: 1600 },
    { time: "10:25", price: 541.1, avgPrice: 540.5, volume: 1750 },
    { time: "10:26", price: 541.0, avgPrice: 540.5, volume: 1900 },
    { time: "10:27", price: 541.3, avgPrice: 540.6, volume: 2100 },
    { time: "10:28", price: 541.5, avgPrice: 540.7, volume: 2300 },
    { time: "10:29", price: 541.7, avgPrice: 540.8, volume: 2500 },
    { time: "10:30", price: 541.8, avgPrice: 540.9, volume: 2800 },
  ],
  ticks: [
    { time: "10:29:01", price: 541.2, volume: 68, side: "B" },
    { time: "10:29:05", price: 541.3, volume: 120, side: "B" },
    { time: "10:29:10", price: 541.3, volume: 156, side: "B" },
    { time: "10:29:13", price: 541.1, volume: 91, side: "S" },
    { time: "10:29:18", price: 541.5, volume: 203, side: "B" },
    { time: "10:29:25", price: 541.7, volume: 177, side: "B" },
    { time: "10:29:33", price: 541.8, volume: 88, side: "B" },
  ],
};

// 本地测试时打开下面两行：
// const result = analyzeStockSnapshot(demoSnapshot);
// console.log(result.brief);

export {
  analyzeStockSnapshot,
  analyzeStockList,
  formatBrief,
  generateSignal,
  analyzePricePosition,
  analyzeMinuteTrend,
  analyzeActiveBuySell,
  analyzeVolume,
};
