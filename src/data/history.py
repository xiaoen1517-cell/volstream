"""历史 K 线检查与补全。"""
from typing import List, Optional

from src.config import CONFIG
from src.db.repository import KlineRepository
from src.exchange.client import ExchangeClient
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 周期分钟数，用于估算应有根数
_TF_MINUTES = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "6h": 360,
    "12h": 720,
    "1d": 1440,
}

# 指标计算至少需要的根数
_MIN_BARS_FOR_INDICATORS = 100


def expected_bar_count(timeframe: str, days: int) -> int:
    """按配置天数估算应有 K 线条数（留 20% 余量，避免边界误判）。"""
    minutes = _TF_MINUTES.get(timeframe)
    if not minutes:
        return _MIN_BARS_FOR_INDICATORS
    full = int(days * 24 * 60 / minutes)
    return max(_MIN_BARS_FOR_INDICATORS, int(full * 0.8))


def ensure_history(
    symbols: List[str],
    days: Optional[int] = None,
    timeframes: Optional[List[str]] = None,
) -> None:
    """
    检查各币种各周期历史是否足够；不足则从交易所拉取并写入。
    足够则跳过，避免每次启动全量重拉。
    """
    days = days or int(CONFIG["app"]["history_days"])
    timeframes = timeframes or list(CONFIG["timeframes"])
    exchange = CONFIG["exchange"]["name"]
    client = ExchangeClient()
    repo = KlineRepository()

    logger.info(
        f"检查历史 K 线: {len(symbols)} 个交易对 × {len(timeframes)} 周期，"
        f"目标约 {days} 天"
    )

    for symbol in symbols:
        for timeframe in timeframes:
            need = expected_bar_count(timeframe, days)
            have = repo.count_klines(symbol, exchange, timeframe)
            if have >= need:
                logger.info(
                    f"【{symbol} · {timeframe}】历史已有 {have} 根（需 ≥{need}），跳过同步"
                )
                continue

            logger.info(
                f"【{symbol} · {timeframe}】历史不足（{have}/{need}），"
                f"开始补全最近 {days} 天…"
            )
            klines = client.fetch_ohlcv(symbol, timeframe, days=days)
            written = repo.save_klines(symbol, client.exchange_name, timeframe, klines)
            logger.info(
                f"【{symbol} · {timeframe}】已写入 {written} 根 K 线"
                f"（库内现有 {repo.count_klines(symbol, exchange, timeframe)} 根）"
            )
