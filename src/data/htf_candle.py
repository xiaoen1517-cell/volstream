"""由低周期 K 线合成更高周期（含未收盘）蜡烛。"""
from datetime import datetime, timezone
from typing import Dict, Optional

import pandas as pd

from src.db.repository import KlineRepository

_TF_SECONDS = {
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
}


def build_htf_candle_from_5m(
    repo: KlineRepository,
    symbol: str,
    exchange: str,
    timeframe: str,
) -> Optional[Dict]:
    """
    用已入库的 5m K 线合成当前更高周期蜡烛（含未收盘）。
    这样 5m 刚收盘写入后，15m/1h/4h 重算能立刻吃到这根 5m。
    """
    seconds = _TF_SECONDS.get(timeframe)
    if not seconds or timeframe == "5m":
        return None

    need = max(120, seconds // 300 + 10)
    df = repo.get_latest_klines(symbol, exchange, "5m", limit=need)
    if df.empty:
        return None

    last_time = pd.Timestamp(df.iloc[-1]["time"])
    if last_time.tzinfo is None:
        last_time = last_time.tz_localize("UTC")
    else:
        last_time = last_time.tz_convert("UTC")
    last_ts = int(last_time.timestamp())
    open_ts = last_ts - (last_ts % seconds)
    open_dt = datetime.fromtimestamp(open_ts, tz=timezone.utc)

    times = pd.to_datetime(df["time"], utc=True)
    window = df.loc[times >= open_dt]
    if window.empty:
        return None

    quote = window["quote_volume"].fillna(0) if "quote_volume" in window else 0
    return {
        "time": open_dt,
        "timestamp_ms": open_ts * 1000,
        "close_timestamp_ms": (open_ts + seconds) * 1000,
        "open": float(window.iloc[0]["open"]),
        "high": float(window["high"].max()),
        "low": float(window["low"].min()),
        "close": float(window.iloc[-1]["close"]),
        "volume": float(window["volume"].sum()),
        "quote_volume": float(quote.sum()) if not isinstance(quote, int) else 0.0,
    }
