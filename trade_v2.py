#!/usr/bin/env python3
"""
OpenClaw 狂暴动量 AI 交易员 Live Edition v4.0
永续合约动量狙击策略

规则：双向狙击 + 贪婪模式 + 14min强退 + 30%熔断
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_DIR = Path("/Users/sonic/.openclaw/workspace/trading-bot")
BASE_URL = "https://fapi.binance.com"
USER_AGENT = "openclaw-momentum-sniper/4.0"
STATUS_FILE = BASE_DIR / "status.json"
TRADES_FILE = BASE_DIR / "trades.json"
THINKING_FILE = BASE_DIR / "thinking.json"
STRATEGY_V2_FILE = BASE_DIR / "strategy_v2.json"

CORE_COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


load_env_file(BASE_DIR / ".env")


def ensure_credentials() -> None:
    if os.getenv("BINANCE_API_KEY") and os.getenv("BINANCE_SECRET_KEY"):
        return
    raise RuntimeError("Missing Binance API credentials.")


@dataclass
class Config:
    """V4 策略配置"""
    version: str = "4.0-momentum-sniper"
    # 标的
    core_coins: list[str] = field(default_factory=lambda: list(CORE_COINS))
    dynamic_pool_size: int = 3
    top_n: int = 7  # core 4 + dynamic 3
    # 仓位
    max_concurrent_positions: int = 3
    position_size_pct: float = 0.10
    # 杠杆 — 主流币(BTC/ETH) 10-15x, 山寨币 7-10x
    leverage_major_low: int = 10
    leverage_major_high: int = 15
    leverage_alt_low: int = 7
    leverage_alt_high: int = 10
    greedy_leverage: int = 20
    greedy_streak: int = 3
    # 微利保护
    micro_profit_trigger: float = 0.006   # 盈利 0.6% 后开始监控
    micro_profit_floor: float = 0.003     # 回撤至 0.3% 强制保本平仓
    # 止盈
    tp1_pct: float = 0.010        # 1.0% 净利平50%
    tp1_close_pct: float = 0.5
    tp2_pct: float = 0.025        # 2.5% 全平
    # 止损
    sl_major: float = 0.010       # 主流币 1.0%
    sl_alt: float = 0.008         # 山寨币 0.8%
    # 超时
    time_exit_minutes: int = 14
    # 冷却
    cooldown_general: int = 60
    cooldown_after_sl: int = 180
    # 市场过滤
    ma_slope_threshold: float = 0.002   # MA20斜率 0.2%
    btc_eth_drop_block: float = 0.02    # BTC/ETH 15min跌幅 > 2% 禁止多单
    doji_threshold: float = 0.50        # 死鱼盘：十字星 > 50%
    # 熔断
    drawdown_pct: float = 0.30
    drawdown_pause_seconds: int = 3600


class BinanceClient:
    """Binance API 客户端"""
    
    def __init__(self, api_key: str = "", secret_key: str = ""):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = BASE_URL
    
    def _sign(self, params: str) -> str:
        return hmac.new(
            self.secret_key.encode(), 
            params.encode(), 
            hashlib.sha256
        ).hexdigest()
    
    def _request(self, endpoint: str, params: dict = None, signed: bool = False) -> dict:
        url = f"{self.base_url}{endpoint}"
        if params:
            query = urlencode(params)
            if signed:
                query += f"&signature={self._sign(query)}"
            url = f"{url}?{query}"
        
        headers = {"User-Agent": USER_AGENT}
        if self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key
        
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode())
        except Exception as e:
            print(f"API Error: {e}")
            return {}
    
    def get_ticker_24h(self) -> list:
        return self._request("/fapi/v1/ticker/24hr") or []
    
    def get_klines(self, symbol: str, interval: str = "1m", limit: int = 60) -> list:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        data = self._request("/fapi/v1/klines", params) or []
        return [
            {
                "time": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            }
            for k in data
        ]
    
    def get_account(self) -> dict:
        timestamp = int(time.time() * 1000)
        params = {"timestamp": timestamp, "recvWindow": 5000}
        return self._request("/fapi/v2/account", params, signed=True) or {}
    
    def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> dict:
        """设置保证金模式为逐仓"""
        timestamp = int(time.time() * 1000)
        params = {
            "symbol": symbol,
            "marginType": margin_type,
            "timestamp": timestamp,
            "recvWindow": 5000,
        }
        query = urlencode(params)
        params["signature"] = self._sign(query)
        try:
            return self._request("/fapi/v1/marginType", params, signed=True) or {}
        except Exception:
            return {}  # 已经是逐仓模式时会报错，忽略
    
    def set_leverage(self, symbol: str, leverage: int) -> dict:
        """设置杠杆倍数"""
        timestamp = int(time.time() * 1000)
        params = {
            "symbol": symbol,
            "leverage": leverage,
            "timestamp": timestamp,
            "recvWindow": 5000,
        }
        query = urlencode(params)
        params["signature"] = self._sign(query)
        return self._request("/fapi/v1/leverage", params, signed=True) or {}
    
    def place_order(self, symbol: str, side: str, order_type: str, 
                    quantity: float = None, price: float = None,
                    reduce_only: bool = False) -> dict:
        timestamp = int(time.time() * 1000)
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "timestamp": timestamp,
            "recvWindow": 5000,
        }
        if quantity:
            params["quantity"] = round(quantity, 3)
        if price:
            params["price"] = round(price, 2)
        if reduce_only:
            params["reduceOnly"] = "true"
        
        query = urlencode(params)
        params["signature"] = self._sign(query)
        
        return self._request("/fapi/v1/order", params, signed=True) or {}


class TechnicalIndicators:
    """技术指标计算"""
    
    @staticmethod
    def sma(values: list, period: int) -> float:
        if len(values) < period:
            return values[-1] if values else 0
        return sum(values[-period:]) / period
    
    @staticmethod
    def atr(klines: list, period: int = 14) -> float:
        if len(klines) < period + 1:
            return 0
        trs = []
        for i in range(1, len(klines)):
            high = klines[i]["high"]
            low = klines[i]["low"]
            prev_close = klines[i-1]["close"]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
        return sum(trs[-period:]) / period if trs else 0
    
    @staticmethod
    def volatility(klines: list, period: int = 15) -> float:
        if not klines:
            return 0
        current_price = klines[-1]["close"]
        if current_price == 0:
            return 0
        atr = TechnicalIndicators.atr(klines, period)
        return (atr / current_price) * 100
    
    @staticmethod
    def ma_slope(ma_current: float, ma_past: float) -> float:
        if ma_past == 0:
            return 0
        return ((ma_current - ma_past) / ma_past) * 100
    
    @staticmethod
    def is_doji(kline: dict, threshold: float = 0.3) -> bool:
        """判断十字星：实体占整根K线高度的比例很小"""
        body = abs(kline["close"] - kline["open"])
        shadow = kline["high"] - kline["low"]
        if shadow == 0:
            return True  # 无波动也算死鱼
        return (body / shadow) < threshold
    
    @staticmethod
    def is_engulfing(prev: dict, curr: dict) -> str:
        """吞没形态检测，返回 'bullish' / 'bearish' / ''"""
        prev_body = prev["close"] - prev["open"]
        curr_body = curr["close"] - curr["open"]
        
        # 看涨吞没：前阴后阳，当前实体完全包裹前一根
        if prev_body < 0 and curr_body > 0:
            if curr["open"] <= prev["close"] and curr["close"] >= prev["open"]:
                return "bullish"
        
        # 看跌吞没：前阳后阴，当前实体完全包裹前一根
        if prev_body > 0 and curr_body < 0:
            if curr["open"] >= prev["close"] and curr["close"] <= prev["open"]:
                return "bearish"
        
        return ""


class CoinScorer:
    """V4 币种评分系统 — 评分 = 15min波动率*0.4 + 成交量爆发*0.3 + 5min涨跌幅*0.3"""
    
    def __init__(self, client: BinanceClient):
        self.client = client
    
    def get_top_coins(self, top_n: int = 20) -> list:
        """获取成交额前N的USDT合约币种"""
        import urllib.request
        
        stable_coins = ['USDCUSDT', 'USDTUSDT', 'FDUSDUSDT', 'USD1USDT', 'USDDUSDT', 'TUSDUSDT', 'BUSDUSDT']
        
        url = "https://api.binance.com/api/v3/ticker/24hr"
        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0')
            with urllib.request.urlopen(req, timeout=10) as response:
                tickers = json.loads(response.read().decode())
        except Exception as e:
            print(f"获取现货数据失败: {e}")
            tickers = self.client.get_ticker_24h()
        
        usdt_pairs = [t for t in tickers if t.get("symbol", "").endswith("USDT") 
                      and t.get("symbol", "") not in stable_coins]
        sorted_tickers = sorted(usdt_pairs, key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
        return [t["symbol"] for t in sorted_tickers[:top_n]]
    
    def score_coin(self, symbol: str) -> float:
        """V4评分公式: 15min波动率*0.4 + 成交量爆发*0.3 + 5min涨跌幅*0.3"""
        klines = self.client.get_klines(symbol, "1m", 20)
        if not klines or len(klines) < 15:
            return 0
        
        # 15min波动率 (ATR / price)
        vol_15m = TechnicalIndicators.volatility(klines[-15:], 15)
        
        # 成交量爆发：最近5根 vs 前10根平均量
        volumes = [k["volume"] for k in klines]
        if len(volumes) >= 15:
            vol_recent = sum(volumes[-5:]) / 5
            vol_prev = sum(volumes[-15:-5]) / 10
            vol_burst = (vol_recent / vol_prev - 1) * 100 if vol_prev > 0 else 0
        else:
            vol_burst = 0
        
        # 5min涨跌幅（绝对值）
        closes = [k["close"] for k in klines]
        if len(closes) >= 5 and closes[-5] > 0:
            change_5m = abs((closes[-1] - closes[-5]) / closes[-5]) * 100
        else:
            change_5m = 0
        
        return vol_15m * 0.4 + vol_burst * 0.3 + change_5m * 0.3
    
    def get_dynamic_pool(self, exclude: list[str], top_n: int = 3) -> list:
        """从成交额Top10（排除核心池）中取评分最高的前N"""
        all_coins = self.get_top_coins(20)
        candidates = [c for c in all_coins if c not in exclude][:10]
        
        scored = []
        for symbol in candidates:
            score = self.score_coin(symbol)
            scored.append((symbol, score))
        
        scored.sort(key=lambda x: x[1], reverse=True)
        return [s[0] for s in scored[:top_n]]


class MomentumStrategy:
    """V4 狂暴动量策略"""
    
    def __init__(self, client: BinanceClient, config: Config):
        self.client = client
        self.config = config
    
    def check_market_filter(self) -> tuple[bool, str, str]:
        """
        战区环境检测
        返回: (ok, reason, zone) zone='long'/'short'/'blocked'
        """
        # BTC/ETH 15min暴跌检测
        for symbol in ["BTCUSDT", "ETHUSDT"]:
            klines = self.client.get_klines(symbol, "1m", 15)
            if len(klines) < 15:
                continue
            chg = (klines[-1]["close"] - klines[0]["close"]) / klines[0]["close"]
            if chg <= -self.config.btc_eth_drop_block:
                return False, f"{symbol} 15m跌{chg*100:.1f}%，禁止多单", "blocked"
        
        # 用BTC判定战区方向：MA5 > MA10 > MA20 为多头区
        btc_klines = self.client.get_klines("BTCUSDT", "1m", 30)
        if len(btc_klines) < 20:
            return True, "K线不足，默认通过", "long"
        
        closes = [k["close"] for k in btc_klines]
        ma5 = TechnicalIndicators.sma(closes, 5)
        ma10 = TechnicalIndicators.sma(closes, 10)
        ma20 = TechnicalIndicators.sma(closes, 20)
        
        # MA20斜率
        ma20_prev = TechnicalIndicators.sma(closes[:-5], 20) if len(closes) > 5 else ma20
        slope = TechnicalIndicators.ma_slope(ma20, ma20_prev)
        
        if ma5 > ma10 > ma20 and slope > self.config.ma_slope_threshold * 100:
            return True, "多头战区", "long"
        elif ma5 < ma10 < ma20 and slope < -self.config.ma_slope_threshold * 100:
            return True, "空头战区", "short"
        
        # 方向不明确但不阻止交易
        return True, "震荡区间", "neutral"
    
    def check_dead_fish(self, symbol: str) -> tuple[bool, str]:
        """死鱼盘检测：15min内十字星K线 > 50%"""
        klines = self.client.get_klines(symbol, "1m", 15)
        if len(klines) < 15:
            return True, "K线不足"
        
        doji_count = sum(1 for k in klines if TechnicalIndicators.is_doji(k))
        ratio = doji_count / len(klines)
        
        if ratio > self.config.doji_threshold:
            return False, f"当前处于死鱼盘（十字星{ratio*100:.0f}%），换场子！"
        return True, "OK"
    
    def identify_direction(self, symbol: str) -> str:
        """通过MA排列判断方向"""
        klines = self.client.get_klines(symbol, "1m", 25)
        if len(klines) < 20:
            return "unknown"
        
        closes = [k["close"] for k in klines]
        ma5 = TechnicalIndicators.sma(closes, 5)
        ma10 = TechnicalIndicators.sma(closes, 10)
        ma20 = TechnicalIndicators.sma(closes, 20)
        
        ma20_prev = TechnicalIndicators.sma(closes[:-5], 20) if len(closes) > 5 else ma20
        slope = TechnicalIndicators.ma_slope(ma20, ma20_prev)
        
        if ma5 > ma10 > ma20 and slope > self.config.ma_slope_threshold * 100:
            return "long"
        elif ma5 < ma10 < ma20 and slope < -self.config.ma_slope_threshold * 100:
            return "short"
        return "unknown"
    
    def check_entry(self, symbol: str, direction: str) -> tuple[bool, list[str]]:
        """
        双向狙击逻辑：3选2
        A: 价格回调/反弹至MA5/MA10附近 (< 0.8%)
        B: 1min出现吞没实体
        C: 缩量后放量突破MA5
        """
        klines = self.client.get_klines(symbol, "1m", 20)
        if len(klines) < 10:
            return False, []
        
        closes = [k["close"] for k in klines]
        volumes = [k["volume"] for k in klines]
        price = closes[-1]
        
        ma5 = TechnicalIndicators.sma(closes, 5)
        ma10 = TechnicalIndicators.sma(closes, 10)
        
        cond = []
        
        # 条件A: 回归 — 价格距MA5或MA10 < 0.8%
        for ma, name in [(ma5, "MA5"), (ma10, "MA10")]:
            if ma > 0:
                dist = abs(price - ma) / ma * 100
                if dist < 0.8:
                    cond.append(f"回归{name}")
                    break
        
        # 条件B: 吞没形态
        if len(klines) >= 2:
            engulf = TechnicalIndicators.is_engulfing(klines[-2], klines[-1])
            if direction == "long" and engulf == "bullish":
                cond.append("看涨吞没")
            elif direction == "short" and engulf == "bearish":
                cond.append("看跌吞没")
        
        # 条件C: 缩量整理后放量突破MA5
        if len(volumes) >= 5:
            # 前3根缩量（递减或低于均量）
            avg_vol = sum(volumes[-8:-3]) / 5 if len(volumes) >= 8 else sum(volumes) / len(volumes)
            recent_shrink = all(v < avg_vol * 0.8 for v in volumes[-4:-1])
            current_burst = volumes[-1] > avg_vol * 1.2
            
            if recent_shrink and current_burst:
                if direction == "long" and price > ma5:
                    cond.append("放量突破")
                elif direction == "short" and price < ma5:
                    cond.append("放量跌破")
        
        return len(cond) >= 2, cond
    
    def get_sl_pct(self, symbol: str) -> float:
        """根据币种类型返回止损比例"""
        if symbol in CORE_COINS:
            return self.config.sl_major
        return self.config.sl_alt
    
    def calc_sl(self, direction: str, entry: float, sl_pct: float) -> float:
        """计算止损价"""
        if direction == "long":
            return entry * (1 - sl_pct)
        return entry * (1 + sl_pct)


class TradingBot:
    """V4 交易机器人"""
    
    def __init__(self, api_key: str = "", secret_key: str = ""):
        self.client = BinanceClient(api_key, secret_key)
        self.config = Config()
        self.scorer = CoinScorer(self.client)
        self.strategy = MomentumStrategy(self.client, self.config)
        
        self.universe = []
        self.trading_coins = []
        self.positions = {}
        self.last_trade = {}
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.pause_until = 0
        self.highest_balance = 0
        self.last_universe_update = 0
        self.last_events = []

    def now_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 直播解说语料库 ──────────────────────────────────────
    COMMENTARY = {
        "scan_start": [
            "🔄 【狂暴模式】新一轮猎杀启动！",
            "🔄 雷达已开启，正在全市场搜索猎物...",
            "🔄 动量雷达扫描中，谁在这个时间点最骚动？",
            "🔄 开始巡逻，看看有没有币种在偷偷搞事情...",
            "🔄 AI之眼已觉醒，扫描全场中...",
            "🔄 V4引擎转速拉满！全市场扫描中...",
            "🔄 开始搜索！如果市场是海洋，我就是那条最敏锐的鲨鱼 🦈",
        ],
        "market_filter_fail": [
            "⛔ {reason}... 大盘太拉跨了，先撤！",
            "⛔ {reason}，看这架势，先空仓看戏 🍿",
            "⛔ {reason}，这种行情开仓等于送钱啊兄弟们",
            "⛔ {reason}，AI也怕被套，苟着！",
            "⛔ {reason}，市场先生今天心情不好，等他冷静再说",
        ],
        "dead_fish": [
            "🐟 {coin}：{reason}",
            "🐟 {coin} 一动不动，这是在装死吗？换场子！",
            "🐟 {coin} 完全没有脉搏，跳过这条死鱼！",
        ],
        "trend_skip": [
            "🔍 扫了一眼 {coin}，方向不明，跳过！",
            "🔍 {coin} 在原地画圈圈，下一个！",
            "🔍 {coin} 趋势不明朗，选择观望",
        ],
        "long_signal": [
            "📈【狙击时刻】检测到 {coin} 动量爆发：{cond}，10倍杠杆出击！",
            "📈 发现猎物！{coin} 多头信号：{cond}，准备冲了！🚀",
            "📈 {coin} 满足 {cond}，教科书级别的多单机会！",
            "📈 注意！{coin} 出现黄金做多点位：{cond} 💪",
        ],
        "short_signal": [
            "📉【狙击时刻】检测到 {coin} 空头动量：{cond}，精准做空！",
            "📉 {coin} 空头信号来了：{cond}！空军出击！",
            "📉 {coin} 弱势信号：{cond}，反手做空 🐻",
        ],
        "open_long": [
            "🎯【出击】{coin} 做多 @ {price}，{lev}x杠杆！让利润飞！",
            "🎯 冲了！{coin} 多单 @ {price} {lev}x，系好安全带 🎢",
            "🎯 {coin} 做多入场 @ {price} {lev}x，信心满满！",
        ],
        "open_short": [
            "🎯【出击】{coin} 做空 @ {price}，{lev}x杠杆！等着它掉！",
            "🎯 空军出击！{coin} 空单 @ {price} {lev}x 🪂",
            "🎯 {coin} 空单入场 @ {price} {lev}x，顺势而为！",
        ],
        "close_profit": [
            "🧾 落袋为安！{coin} 止盈平仓 💰",
            "🧾 {coin} 到达目标，漂亮收割！🤑",
            "🧾 {coin} 利润入账！谢谢市场先生的红包",
        ],
        "close_loss": [
            "🧾 {coin} 触发止损，小亏一笔，下次再战！",
            "🧾 {coin} 认栽了，止损出局。留得青山在 🌲",
            "🧾 {coin} 方向做反，果断止损。亏小钱保大命！",
        ],
        "close_timeout": [
            "🧾 14分钟博弈结束，{coin} 太磨叽，撤单换猎物！",
            "🧾 {coin} 磨了14分钟不动，超时退出！",
            "🧾 {coin} 超时了，AI不喜欢等太久，下一个！",
        ],
        "close_tp1": [
            "🧾 {coin} 1%止盈，平一半！止损移至保本，安心坐等 ✌️",
            "🧾 {coin} 触发第一目标，减仓50%，锁利继续！",
        ],
        "close_micro_profit": [
            "🧾 {coin} 微利保护触发！盈利回撤到0.3%，果断保本出局！",
            "🧾 {coin} 差点到嘴的鸭子飞了，微利保护平仓！",
        ],
        "position_full": [
            "😤 由于仓位已满，错过 {coin} 信号，可惜了！",
            "😤 {coin} 出现信号但3仓已满！只能眼睁睁看着机会溜走...",
            "😤 仓位爆满！{coin} 的机会只能放弃了，下次一定！",
        ],
        "no_signal": [
            "😴 这一轮没找到好机会，继续蹲守...",
            "😴 市场太安静了，AI先打个盹...",
            "😴 暂时没信号，好戏还在后头...",
            "😴 全场静默...不冲动，继续等！",
            "😴 没有机会就是最好的风控！",
            "😴 扫了一圈啥也没有，交易的日常啊朋友们",
        ],
        "universe_update": [
            "📡 V4猎场刷新！核心：{core}，动态：{dynamic}",
            "📡 新一轮选拔完毕！参赛选手：{coins}",
            "📡 从全市场里挑出了这些：{coins}",
        ],
        "greedy_on": [
            "🔥【狂暴模式开启】三连胜手感火热，20倍重仓出击！",
            "🔥 三连赢！贪婪模式激活！杠杆拉到20x！",
            "🔥 连续止盈3笔！AI决定加大火力！20x！",
        ],
        "greedy_off": [
            "💤 贪婪模式关闭，回到正常10x杠杆",
        ],
        "paused_drawdown": [
            "🚨【系统宕机】别看了，AI也得去天台吹吹风，1小时后再回来复仇！",
            "🚨 当日回撤30%，紧急熔断！1小时后复活！",
            "🚨 亏太多了！AI决定闭关修炼1小时后再战",
        ],
    }

    def pick_comment(self, category: str, **kwargs) -> str:
        pool = self.COMMENTARY.get(category, [])
        if not pool:
            return ""
        template = random.choice(pool)
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template

    def add_thought(self, message: str) -> None:
        thoughts = read_json(THINKING_FILE, [])
        thoughts.append({"time": self.now_str(), "thought": message})
        write_json(THINKING_FILE, thoughts[-200:])

    def append_trade_record(self, payload: dict[str, Any]) -> None:
        trades = read_json(TRADES_FILE, [])
        trades.append(payload)
        write_json(TRADES_FILE, trades[-500:])

    def build_open_positions(self) -> tuple[list[dict[str, Any]], float]:
        open_positions = []
        total_unrealized = 0.0
        for symbol, pos in self.positions.items():
            klines = self.client.get_klines(symbol, "1m", 1)
            mark_price = klines[-1]["close"] if klines else pos["entry"]
            qty = float(pos["qty"])
            if pos["direction"] == "long":
                unrealized = (mark_price - pos["entry"]) * qty
            else:
                unrealized = (pos["entry"] - mark_price) * qty
            total_unrealized += unrealized
            open_positions.append({
                "symbol": symbol,
                "direction": pos["direction"],
                "entryPrice": round(float(pos["entry"]), 6),
                "price": round(float(pos["entry"]), 6),
                "markPrice": round(float(mark_price), 6),
                "unrealizedProfit": round(float(unrealized), 4),
                "leverage": pos["leverage"],
                "amount": round(qty, 4),
            })
        return open_positions, total_unrealized

    def update_status(self, events: Optional[list[str]] = None, top_signal: Optional[dict[str, Any]] = None) -> None:
        status = read_json(STATUS_FILE, {})
        balance = self.get_balance()
        open_positions, total_unrealized = self.build_open_positions()

        is_greedy = self.consecutive_wins >= self.config.greedy_streak
        lev_label = f"{'🔥20x狂暴' if is_greedy else '主流10-15x/山寨7-10x'}"

        status.update({
            "last_run": self.now_str(),
            "balance": round(float(balance), 4),
            "equity": round(float(balance + total_unrealized), 4),
            "unrealized_pnl": round(float(total_unrealized), 4),
            "positions": len(open_positions),
            "open_positions": open_positions,
            "mode": "strategy-v4",
            "watchlist": [symbol.replace("USDT", "") for symbol in self.trading_coins],
            "top_signal": top_signal or {"symbol": None, "direction": None, "score": None},
            "events": (events or self.last_events or ["v4 running"])[-8:],
            "strategy_v2": {
                "version": "狂暴动量v4.0",
                "takeProfit": f"+1.0%平50%移保本 / +2.5%全平",
                "stopLoss": f"主流1.0% / 山寨0.8%",
                "leverage": lev_label,
                "positionSize": f"10%仓位，最多{self.config.max_concurrent_positions}持仓",
                "entryLogic": "3选2狙击：回归MA / 吞没形态 / 放量突破",
                "coins": [symbol.replace("USDT", "") for symbol in self.trading_coins],
                "topN": self.config.top_n,
            }
        })
        write_json(STATUS_FILE, status)
    
    def update_universe(self):
        now = time.time()
        if not self.universe or now - self.last_universe_update > 60:  # 每分钟刷新
            print("更新V4币种列表...")
            core = [c for c in self.config.core_coins]
            dynamic = self.scorer.get_dynamic_pool(core, self.config.dynamic_pool_size)
            self.universe = core + dynamic
            self.trading_coins = self.universe[:self.config.top_n]
            self.last_universe_update = now
            
            core_str = ' / '.join(c.replace('USDT', '') for c in core)
            dynamic_str = ' / '.join(c.replace('USDT', '') for c in dynamic) if dynamic else '暂无'
            coins_str = ' / '.join(c.replace('USDT', '') for c in self.trading_coins)
            self.add_thought(self.pick_comment("universe_update", core=core_str, dynamic=dynamic_str, coins=coins_str))
            print(f"V4交易池: {self.trading_coins}")
    
    def get_balance(self) -> float:
        account = self.client.get_account()
        for a in account.get("assets", []):
            if a.get("asset") == "USDT":
                return float(a.get("availableBalance", 0))
        return 0
    
    def is_paused(self) -> bool:
        now = time.time()
        if now < self.pause_until:
            remaining = int(self.pause_until - now)
            print(f"熔断暂停中，剩余{remaining}秒")
            return True
        
        if self.highest_balance > 0:
            bal = self.get_balance()
            dd = (self.highest_balance - bal) / self.highest_balance
            if dd >= self.config.drawdown_pct:
                print(f"回撤{dd*100:.1f}%，触发熔断！暂停1小时")
                self.add_thought(self.pick_comment("paused_drawdown"))
                self.pause_until = now + self.config.drawdown_pause_seconds
                return True
        return False
    
    def get_current_leverage(self, symbol: str) -> int:
        """根据连胜状态和币种类型返回杠杆倍数"""
        if self.consecutive_wins >= self.config.greedy_streak:
            return self.config.greedy_leverage
        # 主流币(BTC/ETH) 10-15x，山寨币 7-10x
        if symbol in ["BTCUSDT", "ETHUSDT"]:
            low, high = self.config.leverage_major_low, self.config.leverage_major_high
        else:
            low, high = self.config.leverage_alt_low, self.config.leverage_alt_high
        # 根据波动率选择：低波动用高杠杆，高波动用低杠杆
        klines = self.client.get_klines(symbol, "1m", 15)
        vol = TechnicalIndicators.volatility(klines, 15) if klines else 0
        if vol < 0.5:
            return high
        elif vol > 1.5:
            return low
        return (low + high) // 2
    
    def open_position(self, symbol: str, direction: str) -> bool:
        now = time.time()
        
        # 冷却
        if symbol in self.last_trade:
            cd = self.config.cooldown_after_sl if self.consecutive_losses > 0 else self.config.cooldown_general
            if now - self.last_trade[symbol] < cd:
                return False
        
        if len(self.positions) >= self.config.max_concurrent_positions:
            coin = symbol.replace('USDT', '')
            self.add_thought(self.pick_comment("position_full", coin=coin))
            return False
        if symbol in self.positions:
            return False
        
        bal = self.get_balance()
        if bal < 10:
            return False
        
        klines = self.client.get_klines(symbol, "1m", 1)
        if not klines:
            return False
        
        price = klines[-1]["close"]
        lev = self.get_current_leverage(symbol)
        size = bal * self.config.position_size_pct * lev / price
        
        # 设置逐仓 + 杠杆
        try:
            self.client.set_margin_type(symbol, "ISOLATED")
        except:
            pass
        try:
            self.client.set_leverage(symbol, lev)
        except:
            pass
        
        side = "BUY" if direction == "long" else "SELL"
        
        try:
            result = self.client.place_order(symbol, side, "MARKET", size)
            if result.get("orderId"):
                self.positions[symbol] = {
                    "direction": direction,
                    "entry": price,
                    "qty": size,
                    "leverage": lev,
                    "open_time": now,
                    "peak_pnl_pct": 0.0,
                }
                self.last_trade[symbol] = now
                coin = symbol.replace('USDT', '')
                print(f"{symbol} 开{'多' if direction=='long' else '空'}成功 {lev}x")
                self.append_trade_record({
                    "time": self.now_str(),
                    "type": side,
                    "symbol": symbol,
                    "amount": round(float(size), 4),
                    "price": round(float(price), 6),
                    "pnl": 0.0,
                    "reason": f"V4狙击开仓",
                    "balance": round(float(self.get_balance()), 4),
                    "leverage": lev,
                    "direction": direction,
                    "tradeAction": "OPEN",
                })
                cat = "open_long" if direction == "long" else "open_short"
                self.add_thought(self.pick_comment(cat, coin=coin, price=f"{price:.4f}", lev=lev))
                return True
        except Exception as e:
            print(f"开仓失败: {e}")
        return False

    def close_position(self, symbol: str, reason: str):
        if symbol not in self.positions:
            return
        pos = self.positions[symbol]
        side = "SELL" if pos["direction"] == "long" else "BUY"
        
        try:
            klines = self.client.get_klines(symbol, "1m", 1)
            close_price = klines[-1]["close"] if klines else pos["entry"]
            self.client.place_order(symbol, side, "MARKET", pos["qty"], reduce_only=True)
            realized = (close_price - pos["entry"]) * pos["qty"] if pos["direction"] == "long" else (pos["entry"] - close_price) * pos["qty"]
            coin = symbol.replace('USDT', '')
            
            # 解说
            if reason == "time_exit":
                self.add_thought(self.pick_comment("close_timeout", coin=coin))
            elif reason in ["stop_loss"] or realized < 0:
                self.add_thought(self.pick_comment("close_loss", coin=coin))
            else:
                self.add_thought(self.pick_comment("close_profit", coin=coin))
            
            self.append_trade_record({
                "time": self.now_str(),
                "type": side,
                "symbol": symbol,
                "amount": round(float(pos["qty"]), 4),
                "price": round(float(close_price), 6),
                "pnl": round(float(realized), 4),
                "reason": f"V4平仓: {reason}",
                "balance": round(float(self.get_balance()), 4),
                "leverage": pos["leverage"],
                "direction": pos["direction"],
                "tradeAction": "CLOSE",
            })
            del self.positions[symbol]
            print(f"{symbol} 平仓: {reason}, PnL: {realized:.4f}")
            
            # 连胜/连亏统计
            if realized > 0:
                self.consecutive_wins += 1
                self.consecutive_losses = 0
                if self.consecutive_wins == self.config.greedy_streak:
                    self.add_thought(self.pick_comment("greedy_on"))
            else:
                self.consecutive_losses += 1
                if self.consecutive_wins >= self.config.greedy_streak:
                    self.add_thought(self.pick_comment("greedy_off"))
                self.consecutive_wins = 0
                
        except Exception as e:
            print(f"平仓失败: {e}")
    
    def check_positions(self):
        now = time.time()
        for symbol, pos in list(self.positions.items()):
            # 14分钟强制退出
            hold_mins = (now - pos["open_time"]) / 60
            if hold_mins >= self.config.time_exit_minutes:
                self.close_position(symbol, "time_exit")
                continue
            
            # 获取当前价格
            klines = self.client.get_klines(symbol, "1m", 1)
            if not klines:
                continue
            price = klines[-1]["close"]
            entry = pos["entry"]
            d = pos["direction"]
            
            pnl_pct = (price - entry) / entry if d == "long" else (entry - price) / entry
            
            # 硬止损
            sl_pct = self.strategy.get_sl_pct(symbol)
            if pnl_pct <= -sl_pct:
                self.close_position(symbol, "stop_loss")
                continue
            
            # 止盈2: 2.5% 全平
            if pnl_pct >= self.config.tp2_pct:
                self.close_position(symbol, "tp2_full")
                continue
            
            # 止盈1: 1.0% 平50%并移至保本
            if pnl_pct >= self.config.tp1_pct and "tp1_triggered" not in pos:
                pos["tp1_triggered"] = True
                qty_half = pos["qty"] * self.config.tp1_close_pct
                reduce_side = "SELL" if d == "long" else "BUY"
                try:
                    self.client.place_order(symbol, reduce_side, "MARKET", qty_half, reduce_only=True)
                    pos["qty"] -= qty_half
                    pos["entry"] = price  # 止损移至保本
                    coin = symbol.replace('USDT', '')
                    self.add_thought(self.pick_comment("close_tp1", coin=coin))
                    print(f"{symbol} TP1触发，减仓50%，止损移至保本")
                except Exception as e:
                    print(f"TP1减仓失败: {e}")
            
            # 微利保护: 盈利达0.6%后，记录峰值；回撤至0.3%强制保本
            if pnl_pct > pos.get("peak_pnl_pct", 0):
                pos["peak_pnl_pct"] = pnl_pct
            
            if (pos.get("peak_pnl_pct", 0) >= self.config.micro_profit_trigger
                    and pnl_pct <= self.config.micro_profit_floor
                    and "tp1_triggered" not in pos):
                coin = symbol.replace('USDT', '')
                self.add_thought(self.pick_comment("close_micro_profit", coin=coin))
                self.close_position(symbol, "micro_profit_protect")
                continue
    
    def scan_and_trade(self) -> tuple[list[str], Optional[dict[str, Any]]]:
        events = []
        top_signal = None
        self.update_universe()
        
        # 市场过滤
        ok, reason, zone = self.strategy.check_market_filter()
        if not ok:
            events.append(reason)
            self.add_thought(self.pick_comment("market_filter_fail", reason=reason))
            return events, top_signal
        
        # 按优先级排序：核心池优先
        sorted_coins = sorted(
            self.trading_coins,
            key=lambda c: (0 if c in CORE_COINS else 1)
        )
        
        for symbol in sorted_coins:
            coin = symbol.replace('USDT', '')
            
            # 死鱼盘检测
            ok, fish_reason = self.strategy.check_dead_fish(symbol)
            if not ok:
                events.append(f"{coin}: {fish_reason}")
                self.add_thought(self.pick_comment("dead_fish", coin=coin, reason=fish_reason))
                continue
            
            # 方向判定
            direction = self.strategy.identify_direction(symbol)
            
            # 如果大盘禁多，只允许做空
            if zone == "blocked" and direction == "long":
                events.append(f"{coin}: 大盘禁多")
                continue
            
            if direction == "unknown":
                events.append(f"{coin}: 方向不明")
                self.add_thought(self.pick_comment("trend_skip", coin=coin))
                continue
            
            if top_signal is None:
                top_signal = {"symbol": symbol, "direction": direction, "score": None}
            
            # 入场检测
            ok, cond = self.strategy.check_entry(symbol, direction)
            if ok:
                cond_str = ' / '.join(cond)
                print(f"{symbol} {'多' if direction == 'long' else '空'}单信号: {cond_str}")
                events.append(f"{coin} {'做多' if direction == 'long' else '做空'} {'/'.join(cond)}")
                
                cat = "long_signal" if direction == "long" else "short_signal"
                self.add_thought(self.pick_comment(cat, coin=coin, cond=cond_str))
                self.open_position(symbol, direction)
        
        return events, top_signal
    
    def tick(self) -> None:
        events = [f"V4扫描 {datetime.now().strftime('%H:%M:%S')}"]
        self.add_thought(self.pick_comment("scan_start"))
        self.check_positions()
        scan_events, top_signal = self.scan_and_trade()
        events.extend(scan_events)
        if len(events) == 1:
            events.append("no candidate")
            self.add_thought(self.pick_comment("no_signal"))
        self.last_events = events[-8:]
        bal = self.get_balance()
        if bal > self.highest_balance:
            self.highest_balance = bal
        self.update_status(events=self.last_events, top_signal=top_signal)
    
    def run(self):
        print("=" * 50)
        print("狂暴动量策略 v4.0 启动")
        print("=" * 50)
        
        self.highest_balance = self.get_balance()
        
        while True:
            try:
                if self.is_paused():
                    self.update_status(events=["熔断暂停中..."])
                    time.sleep(60)
                    continue

                self.tick()
                time.sleep(60)
                
            except KeyboardInterrupt:
                print("\n停止")
                break
            except Exception as e:
                print(f"错误: {e}")
                time.sleep(60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["run", "status", "run-once"])
    args = parser.parse_args()

    ensure_credentials()
    api_key = os.getenv("BINANCE_API_KEY", "")
    secret_key = os.getenv("BINANCE_SECRET_KEY", "")
    
    bot = TradingBot(api_key, secret_key)
    
    if args.cmd == "run":
        bot.run()
    elif args.cmd == "run-once":
        bot.highest_balance = bot.get_balance()
        bot.tick()
    elif args.cmd == "status":
        print(f"余额: {bot.get_balance()}")
        print(f"持仓: {bot.positions}")


if __name__ == "__main__":
    main()
