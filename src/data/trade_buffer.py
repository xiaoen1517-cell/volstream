from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List

from src.config import CONFIG


class TradeBuffer:
    def __init__(self):
        self.timeframes = CONFIG["timeframes"]
        self._buffers: Dict[str, List[dict]] = defaultdict(list)

    def add(self, timeframe: str, trade: dict):
        """将成交数据加入对应周期的缓存。"""
        self._buffers[timeframe].append(trade)

    def flush(self, timeframe: str) -> List[dict]:
        """K 线闭合后取出该周期所有成交并清空。"""
        trades = self._buffers[timeframe]
        self._buffers[timeframe] = []
        return trades

    def peek(self, timeframe: str) -> List[dict]:
        """查看缓冲中的成交，不清空（用于未收盘大周期的临时重算）。"""
        return list(self._buffers[timeframe])

    def count(self, timeframe: str) -> int:
        return len(self._buffers[timeframe])
