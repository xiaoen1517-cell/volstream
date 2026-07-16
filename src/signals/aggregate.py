from datetime import datetime, timezone
from typing import Dict, List

import pandas as pd

from src.analytics.iceberg_detector import IcebergDetector
from src.analytics.volume_profile import VolumeProfile
from src.analytics.whale_detector import WhaleDetector
from src.config import CONFIG
from src.db.repository import AnalysisRepository, KlineRepository, WhaleTradeRepository
from src.indicators.price_volume import calculate_all
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SignalAggregator:
    def __init__(self, symbol: str, exchange: str):
        self.symbol = symbol
        self.exchange = exchange
        self.kline_repo = KlineRepository()
        self.analysis_repo = AnalysisRepository()
        self.whale_repo = WhaleTradeRepository()
        self.weights = CONFIG["weights"]

    async def analyze(self, timeframe: str, closed_kline: dict, trades: List[dict]):
        limit = 100
        df = self.kline_repo.get_latest_klines(
            self.symbol, self.exchange, timeframe, limit=limit
        )
        if df.empty:
            logger.warning(f"{self.symbol} {timeframe} 无足够 K 线数据")
            return

        df = calculate_all(df)
        latest = df.iloc[-1]

        # Volume Profile
        vp = VolumeProfile(df=df, trades=trades)
        profile = vp.calculate()

        # Whale
        whale = WhaleDetector().analyze(trades)
        if whale["whale_trades"]:
            self.whale_repo.save(
                [
                    {
                        "time": t["time"],
                        "symbol": self.symbol,
                        "exchange": self.exchange,
                        "trade_id": t["trade_id"],
                        "price": t["price"],
                        "amount": t["amount"],
                        "quote_amount": t["quote_amount"],
                        "side": "sell" if t.get("is_buyer_maker", False) else "buy",
                    }
                    for t in whale["whale_trades"]
                ]
            )

        # Iceberg
        iceberg = IcebergDetector().analyze(trades)

        # 单周期信号打分
        single_signal, single_strength, reason = self._single_signal(
            latest, profile, whale, iceberg
        )

        result = {
            "time": closed_kline["time"],
            "symbol": self.symbol,
            "exchange": self.exchange,
            "timeframe": timeframe,
            "ema_12": float(latest["ema_12"]),
            "ema_26": float(latest["ema_26"]),
            "macd": float(latest["macd"]),
            "macd_signal": float(latest["macd_signal"]),
            "rsi": float(latest["rsi"]),
            "vwap": float(latest["vwap"]),
            "obv": float(latest["obv"]),
            "delta": float(latest["delta"]),
            "cvd": float(latest["cvd"]),
            "atr": float(latest["atr"]),
            "poc": profile.get("poc"),
            "value_area_high": profile.get("value_area_high"),
            "value_area_low": profile.get("value_area_low"),
            "whale_buy_ratio": whale["whale_buy_ratio"],
            "whale_sell_ratio": whale["whale_sell_ratio"],
            "iceberg_score": iceberg["iceberg_score"],
            "signal": single_signal,
            "signal_strength": single_strength,
            "reason": reason,
        }
        self.analysis_repo.save(result)

        # 多周期聚合
        self._aggregate()

    def _single_signal(
        self, latest: pd.Series, profile: Dict, whale: Dict, iceberg: Dict
    ):
        score = 0.0
        reasons = []

        # EMA 趋势
        if latest["ema_12"] > latest["ema_26"]:
            score += 20
            reasons.append("EMA12 上穿 EMA26")
        elif latest["ema_12"] < latest["ema_26"]:
            score -= 20
            reasons.append("EMA12 下穿 EMA26")

        # MACD
        if latest["macd"] > latest["macd_signal"]:
            score += 15
            reasons.append("MACD 在 Signal 上方")
        else:
            score -= 15
            reasons.append("MACD 在 Signal 下方")

        # RSI
        if latest["rsi"] > 50:
            score += 10
        else:
            score -= 10
        if latest["rsi"] > 70:
            score -= 10
            reasons.append("RSI 超买")
        elif latest["rsi"] < 30:
            score += 10
            reasons.append("RSI 超卖")

        # Volume Profile
        close = latest["close"]
        poc = profile.get("poc")
        if poc:
            if close > profile.get("value_area_high", close):
                score += 15
                reasons.append("价格突破 Value Area 上轨")
            elif close < profile.get("value_area_low", close):
                score -= 15
                reasons.append("价格跌破 Value Area 下轨")

        # Whale
        ratio_diff = whale["whale_buy_ratio"] - whale["whale_sell_ratio"]
        score += ratio_diff * 20
        if abs(ratio_diff) > 0.2:
            side = "买方" if ratio_diff > 0 else "卖方"
            reasons.append(f"大单{side}占优")

        # Iceberg
        if iceberg.get("iceberg_score", 0) >= CONFIG["analytics"]["iceberg_score_threshold"]:
            if iceberg.get("iceberg_side") == "buy":
                score += 10
                reasons.append("检测到买方冰山订单")
            else:
                score -= 10
                reasons.append("检测到卖方冰山订单")

        score = max(-100, min(100, score))
        if score > 20:
            signal = "Bullish"
        elif score < -20:
            signal = "Bearish"
        else:
            signal = "Neutral"

        return signal, abs(score), "；".join(reasons) if reasons else "无明显信号"

    def _aggregate(self):
        df = self.analysis_repo.get_latest(
            self.symbol, self.exchange, list(CONFIG["timeframes"]), limit=1
        )
        if df.empty or len(df) < len(CONFIG["timeframes"]):
            return

        total_score = 0.0
        total_weight = 0.0
        details = []
        for _, row in df.iterrows():
            tf = row["timeframe"]
            weight = self.weights.get(tf, 0.0)
            direction = 1 if row["signal"] == "Bullish" else (-1 if row["signal"] == "Bearish" else 0)
            score = direction * row["signal_strength"]
            total_score += score * weight
            total_weight += weight
            details.append(f"{tf}: {row['signal']}({row['signal_strength']:.1f})")

        if total_weight == 0:
            return

        final_score = total_score / total_weight
        strength = abs(final_score)
        if strength >= CONFIG["signal"]["strength_threshold"]["strong"]:
            label = "STRONG_BULLISH" if final_score > 0 else "STRONG_BEARISH"
        elif strength >= CONFIG["signal"]["strength_threshold"]["moderate"]:
            label = "BULLISH" if final_score > 0 else "BEARISH"
        else:
            label = "NEUTRAL"

        logger.info(
            f"[共振] {self.symbol} 最终信号: {label} | 强度: {strength:.1f} | "
            f"明细: {', '.join(details)}"
        )
