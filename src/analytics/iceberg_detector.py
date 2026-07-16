from collections import defaultdict
from typing import Dict, List

from src.config import CONFIG


class IcebergDetector:
    def __init__(self):
        self.cfg = CONFIG["analytics"]

    def analyze(self, trades: List[dict]) -> Dict:
        """
        基于成交数据检测冰山订单迹象。
        启发式规则：同一价位在短时间内出现多次接近阈值的大单成交，
        且买方/卖方方向一致，认为存在冰山订单拆分执行的可能。
        """
        if len(trades) < self.cfg["iceberg_lookback_trades"]:
            return {"iceberg_score": 0.0, "iceberg_level": None, "iceberg_side": None}

        threshold = self.cfg["whale_threshold_usd"]
        price_groups = defaultdict(lambda: {"buy": 0.0, "sell": 0.0, "count": 0})

        for t in trades:
            if t["quote_amount"] < threshold * 0.5:
                continue
            price = round(t["price"], 2)
            side = "sell" if t.get("is_buyer_maker", False) else "buy"
            price_groups[price][side] += t["quote_amount"]
            price_groups[price]["count"] += 1

        if not price_groups:
            return {"iceberg_score": 0.0, "iceberg_level": None, "iceberg_side": None}

        # 找出最具冰山特征的价位
        best_score = 0.0
        best_level = None
        best_side = None

        for price, data in price_groups.items():
            if data["count"] < 3:
                continue
            total = data["buy"] + data["sell"]
            if total == 0:
                continue
            dominance = max(data["buy"], data["sell"]) / total
            repetition = min(data["count"] / 10.0, 1.0)
            score = dominance * repetition
            if score > best_score:
                best_score = score
                best_level = price
                best_side = "buy" if data["buy"] > data["sell"] else "sell"

        threshold_score = self.cfg["iceberg_score_threshold"]
        return {
            "iceberg_score": round(best_score, 4),
            "iceberg_level": best_level if best_score >= threshold_score else None,
            "iceberg_side": best_side if best_score >= threshold_score else None,
        }
