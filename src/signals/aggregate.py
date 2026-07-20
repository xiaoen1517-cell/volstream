from datetime import datetime, timezone
from typing import Dict, List

import pandas as pd

from src.analytics.iceberg_detector import IcebergDetector
from src.analytics.volume_profile import VolumeProfile
from src.analytics.whale_detector import WhaleDetector
from src.config import CONFIG
from src.db.repository import AnalysisRepository, KlineRepository, WhaleTradeRepository
from src.indicators.price_volume import calculate_all
from src.utils.exchange_time import format_kline_period
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

    async def analyze(
        self,
        timeframe: str,
        closed_kline: dict,
        trades: List[dict],
        *,
        emit_resonance: bool = True,
        quiet: bool = False,
    ):
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

        poc = profile.get("poc")
        support = profile.get("value_area_low")  # VAL → 支撑
        resistance = profile.get("value_area_high")  # VAH → 压力

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
            "poc": poc,
            "value_area_high": resistance,
            "value_area_low": support,
            "whale_buy_ratio": whale["whale_buy_ratio"],
            "whale_sell_ratio": whale["whale_sell_ratio"],
            "iceberg_score": iceberg["iceberg_score"],
            "signal": single_signal,
            "signal_strength": single_strength,
            "reason": reason,
        }
        self.analysis_repo.save(result)

        period = format_kline_period(closed_kline, timeframe)
        if not quiet:
            logger.info(
                f"【{self.symbol} · {_tf_label(timeframe)} · {period}】"
                f"趋势{_signal_cn(single_signal)}（强度 {single_strength:.0f}）｜"
                f"成交密集区 {_fmt_price(poc)}，"
                f"支撑 {_fmt_price(support)}，压力 {_fmt_price(resistance)}"
                + (f"｜依据：{reason}" if reason and reason != "无明显信号" else "")
            )

        # 仅在外部显式要求时共振（5m 收盘重算完四周期后再聚合）
        if timeframe == "5m" and emit_resonance:
            self._aggregate(closed_kline)

    async def on_5m_close(
        self,
        kline_5m: dict,
        trades_5m: List[dict],
        higher_tf_trades: Dict[str, List[dict]],
    ):
        """
        5m 收盘：先分析 5m，再按最新 5m 合成并重算 15m/1h/4h，最后共振。
        这样大周期指标会包含刚收盘的这根 5m，而不会仍停留在上一根大周期收盘时。
        """
        from src.data.htf_candle import build_htf_candle_from_5m

        await self.analyze(
            "5m", kline_5m, trades_5m, emit_resonance=False, quiet=False
        )

        for timeframe in CONFIG["timeframes"]:
            if timeframe == "5m":
                continue
            htf = build_htf_candle_from_5m(
                self.kline_repo, self.symbol, self.exchange, timeframe
            )
            if not htf:
                logger.warning(
                    f"【{self.symbol} · {_tf_label(timeframe)}】无法由 5m 合成，跳过重算"
                )
                continue

            self.kline_repo.save_klines(
                self.symbol,
                self.exchange,
                timeframe,
                [
                    [
                        int(htf["timestamp_ms"]),
                        htf["open"],
                        htf["high"],
                        htf["low"],
                        htf["close"],
                        htf["volume"],
                        htf.get("quote_volume") or 0,
                    ]
                ],
            )
            await self.analyze(
                timeframe,
                htf,
                higher_tf_trades.get(timeframe, []),
                emit_resonance=False,
                quiet=False,
            )

        self._aggregate(kline_5m)

    async def bootstrap_from_klines(self) -> int:
        """用库内最新 K 线为各周期打底 analysis，不触发共振推送。"""
        from src.utils.exchange_time import resolve_close_ms

        seeded = 0
        for timeframe in CONFIG["timeframes"]:
            df = self.kline_repo.get_latest_klines(
                self.symbol, self.exchange, timeframe, limit=100
            )
            if df.empty:
                logger.warning(
                    f"【{self.symbol} · {_tf_label(timeframe)}】无历史 K 线，跳过打底"
                )
                continue

            latest = df.iloc[-1]
            open_time = latest["time"]
            if getattr(open_time, "tzinfo", None) is None:
                open_time = open_time.replace(tzinfo=timezone.utc)
            open_ms = int(open_time.timestamp() * 1000)
            closed_kline = {
                "time": open_time,
                "timestamp_ms": open_ms,
                "close_timestamp_ms": resolve_close_ms(open_ms, timeframe),
                "open": float(latest["open"]),
                "high": float(latest["high"]),
                "low": float(latest["low"]),
                "close": float(latest["close"]),
                "volume": float(latest["volume"]),
                "quote_volume": float(latest.get("quote_volume") or 0),
            }
            await self.analyze(
                timeframe,
                closed_kline,
                trades=[],
                emit_resonance=False,
                quiet=True,
            )
            seeded += 1
            logger.info(
                f"【{self.symbol} · {_tf_label(timeframe)}】"
                f"已用历史 K 线打底分析（{format_kline_period(closed_kline, timeframe)}）"
            )
        return seeded

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
                reasons.append("价格突破压力区")
            elif close < profile.get("value_area_low", close):
                score -= 15
                reasons.append("价格跌破支撑区")

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

    def _aggregate(self, closed_kline: dict):
        timeframes = list(CONFIG["timeframes"])
        df = self.analysis_repo.get_latest(
            self.symbol, self.exchange, timeframes, limit=1
        )
        period = format_kline_period(closed_kline, "5m")
        if df.empty or len(df) < len(timeframes):
            logger.warning(
                f"【{self.symbol} · {period}】5 分钟已收盘，但四周期数据还没齐"
                f"（已有 {len(df)}/{len(timeframes)}），稍后再看共振。"
            )
            return

        # 按配置中的周期顺序输出
        by_tf = {row["timeframe"]: row for _, row in df.iterrows()}

        total_score = 0.0
        total_weight = 0.0
        detail_lines = []
        for tf in timeframes:
            row = by_tf.get(tf)
            if row is None:
                continue
            weight = self.weights.get(tf, 0.0)
            direction = 1 if row["signal"] == "Bullish" else (-1 if row["signal"] == "Bearish" else 0)
            score = direction * row["signal_strength"]
            total_score += score * weight
            total_weight += weight
            detail_lines.append(
                f"  · {_tf_label(tf)}：{_signal_cn(row['signal'])}"
                f"（强度 {row['signal_strength']:.0f}，权重 {weight:.0%}）｜"
                f"密集区 {_fmt_price(row.get('poc'))}，"
                f"支撑 {_fmt_price(row.get('value_area_low'))}，"
                f"压力 {_fmt_price(row.get('value_area_high'))}"
            )

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

        hint = _resonance_hint(label)
        message = (
            f"【{self.symbol} · 四周期共振】\n"
            f"交易所K线：{period}\n"
            f"结论：{_label_cn(label)}（强度 {strength:.0f}/100）\n"
            f"{hint}\n"
            f"\n分周期：\n"
            + "\n".join(detail_lines)
        )
        logger.info(message)

        from src.notify.telegram import send_message

        if send_message(message):
            logger.info(f"【{self.symbol} · {period}】共振结果已推送到 Telegram")


def _tf_label(tf: str) -> str:
    return {"5m": "5分钟", "15m": "15分钟", "1h": "1小时", "4h": "4小时"}.get(tf, tf)


def _signal_cn(signal: str) -> str:
    return {"Bullish": "看涨", "Bearish": "看跌", "Neutral": "中性"}.get(signal, signal)


def _label_cn(label: str) -> str:
    return {
        "STRONG_BULLISH": "强势看涨",
        "BULLISH": "偏多",
        "NEUTRAL": "观望 / 中性",
        "BEARISH": "偏空",
        "STRONG_BEARISH": "强势看跌",
    }.get(label, label)


def _resonance_hint(label: str) -> str:
    return {
        "STRONG_BULLISH": "多周期同向偏多，可关注顺势做多机会",
        "BULLISH": "整体偏多，注意回踩支撑后的反应",
        "NEUTRAL": "多空分歧或动能不足，建议观望",
        "BEARISH": "整体偏空，注意反弹压力位的压制",
        "STRONG_BEARISH": "多周期同向偏空，可关注顺势做空机会",
    }.get(label, "")


def _fmt_price(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "暂无"
    return f"{float(value):,.2f}"
