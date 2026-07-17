import pandas as pd

from src.config import CONFIG


class KlineStore:
    def __init__(self):
        self.timeframes = CONFIG["timeframes"]
        self._buffers = {tf: [] for tf in self.timeframes}

    def update(self, timeframe: str, kline: dict):
        """WebSocket 推送的 K 线更新，闭合时返回 True。"""
        self._buffers[timeframe] = [kline]
        return kline.get("is_closed", False)

    def latest(self, timeframe: str) -> dict:
        if self._buffers[timeframe]:
            return self._buffers[timeframe][-1]
        return {}
