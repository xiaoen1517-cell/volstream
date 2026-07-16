from typing import Dict, List

from src.config import CONFIG


class WhaleDetector:
    def __init__(self, threshold_usd: float = None):
        self.threshold = threshold_usd or CONFIG["analytics"]["whale_threshold_usd"]

    def analyze(self, trades: List[dict]) -> Dict:
        """分析逐笔成交中的大单行为。"""
        whale_buys = []
        whale_sells = []

        for t in trades:
            if t["quote_amount"] < self.threshold:
                continue
            side = self._infer_side(t)
            if side == "buy":
                whale_buys.append(t)
            else:
                whale_sells.append(t)

        buy_volume = sum(t["quote_amount"] for t in whale_buys)
        sell_volume = sum(t["quote_amount"] for t in whale_sells)
        total = buy_volume + sell_volume

        buy_ratio = buy_volume / total if total > 0 else 0.0
        sell_ratio = sell_volume / total if total > 0 else 0.0

        return {
            "whale_buy_count": len(whale_buys),
            "whale_sell_count": len(whale_sells),
            "whale_buy_volume": buy_volume,
            "whale_sell_volume": sell_volume,
            "whale_buy_ratio": buy_ratio,
            "whale_sell_ratio": sell_ratio,
            "whale_trades": whale_buys + whale_sells,
        }

    @staticmethod
    def _infer_side(trade: dict) -> str:
        """根据买方/卖方 maker 判断主动方向。"""
        return "sell" if trade.get("is_buyer_maker", False) else "buy"
