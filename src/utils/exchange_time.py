"""交易所 K 线时间工具。"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Union
from zoneinfo import ZoneInfo

# 展示用时区：与国内交易习惯一致；边界仍由交易所 UTC 开收盘决定
DISPLAY_TZ = ZoneInfo("Asia/Shanghai")

_TF_DELTA = {
    "1m": timedelta(minutes=1),
    "3m": timedelta(minutes=3),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "2h": timedelta(hours=2),
    "4h": timedelta(hours=4),
    "6h": timedelta(hours=6),
    "12h": timedelta(hours=12),
    "1d": timedelta(days=1),
}


def timeframe_delta(timeframe: str) -> timedelta:
    if timeframe not in _TF_DELTA:
        raise ValueError(f"未知周期: {timeframe}")
    return _TF_DELTA[timeframe]


def resolve_close_ms(open_ms: int, timeframe: str, close_ms: Optional[int] = None) -> int:
    if close_ms is not None:
        return int(close_ms)
    open_dt = datetime.fromtimestamp(open_ms / 1000, tz=timezone.utc)
    return int((open_dt + timeframe_delta(timeframe)).timestamp() * 1000)


def format_candle_period(
    open_ms: int,
    timeframe: str,
    close_ms: Optional[int] = None,
) -> str:
    """格式化为交易所 K 线时间段，例如 2026-07-20 21:15–21:20。"""
    end_ms = resolve_close_ms(open_ms, timeframe, close_ms)
    open_dt = datetime.fromtimestamp(open_ms / 1000, tz=timezone.utc).astimezone(DISPLAY_TZ)
    close_dt = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).astimezone(DISPLAY_TZ)
    # Binance 收盘时间常为下一根开盘，展示为开–收 即可
    if open_dt.date() == close_dt.date():
        return f"{open_dt:%Y-%m-%d %H:%M}–{close_dt:%H:%M}"
    return f"{open_dt:%Y-%m-%d %H:%M}–{close_dt:%Y-%m-%d %H:%M}"


def format_kline_period(kline: dict, timeframe: str) -> str:
    open_ms = int(kline.get("timestamp_ms") or 0)
    close_ms = kline.get("close_timestamp_ms")
    return format_candle_period(open_ms, timeframe, close_ms)


def as_utc_datetime(value: Union[datetime, int, float]) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
