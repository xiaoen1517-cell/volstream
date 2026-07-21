from typing import Dict, List

import numpy as np
import pandas as pd

from src.config import CONFIG


class VolumeProfile:
    def __init__(self, df: pd.DataFrame = None, trades: List[dict] = None):
        self.df = df
        self.trades = trades or []
        self.cfg = CONFIG["analytics"]

    @staticmethod
    def _empty() -> Dict:
        return {
            "poc": None,
            "value_area_high": None,
            "value_area_low": None,
            "poc_volume": None,
            "poc_trade_count": None,
            "total_volume": None,
            "poc_volume_ratio": None,
        }

    def from_trades(self, trades: List[dict]) -> Dict:
        """基于逐笔成交计算 Volume Profile。"""
        if not trades:
            return self._empty()

        prices = np.array([t["price"] for t in trades], dtype=float)
        volumes = np.array([t["amount"] for t in trades], dtype=float)

        bins = self.cfg["volume_profile_bins"]
        hist, bin_edges = np.histogram(prices, bins=bins, weights=volumes)
        max_idx = int(np.argmax(hist))
        poc = (bin_edges[max_idx] + bin_edges[max_idx + 1]) / 2
        poc_volume = float(hist[max_idx])
        # 落在 POC 价格桶内的成交笔数
        in_poc = (prices >= bin_edges[max_idx]) & (prices < bin_edges[max_idx + 1])
        # 右端最后一桶用 <= 包含边界
        if max_idx == len(hist) - 1:
            in_poc = (prices >= bin_edges[max_idx]) & (prices <= bin_edges[max_idx + 1])
        poc_trade_count = int(np.count_nonzero(in_poc))

        total_volume = float(volumes.sum())
        target_volume = total_volume * self.cfg["value_area_ratio"]

        sorted_indices = np.argsort(hist)[::-1]
        cumulative = 0.0
        selected_bins = []
        for idx in sorted_indices:
            cumulative += hist[idx]
            selected_bins.append(idx)
            if cumulative >= target_volume:
                break

        if selected_bins:
            low_idx = min(selected_bins)
            high_idx = max(selected_bins)
            value_area_low = bin_edges[low_idx]
            value_area_high = bin_edges[high_idx + 1]
        else:
            value_area_low = value_area_high = poc

        return {
            "poc": float(poc),
            "value_area_high": float(value_area_high),
            "value_area_low": float(value_area_low),
            "poc_volume": poc_volume,
            "poc_trade_count": poc_trade_count,
            "total_volume": total_volume,
            "poc_volume_ratio": (poc_volume / total_volume) if total_volume > 0 else None,
        }

    def from_klines(self) -> Dict:
        """基于 K 线数据近似计算 Volume Profile（备用）。"""
        if self.df is None or self.df.empty:
            return self._empty()

        typical = (self.df["high"] + self.df["low"] + self.df["close"]) / 3
        bins = self.cfg["volume_profile_bins"]
        hist, bin_edges = np.histogram(typical, bins=bins, weights=self.df["volume"])
        max_idx = int(np.argmax(hist))
        poc = (bin_edges[max_idx] + bin_edges[max_idx + 1]) / 2
        poc_volume = float(hist[max_idx])
        total_volume = float(self.df["volume"].sum())
        target_volume = total_volume * self.cfg["value_area_ratio"]
        sorted_indices = np.argsort(hist)[::-1]
        cumulative = 0.0
        selected_bins = []
        for idx in sorted_indices:
            cumulative += hist[idx]
            selected_bins.append(idx)
            if cumulative >= target_volume:
                break

        low_idx = min(selected_bins)
        high_idx = max(selected_bins)
        return {
            "poc": float(poc),
            "value_area_high": float(bin_edges[high_idx + 1]),
            "value_area_low": float(bin_edges[low_idx]),
            "poc_volume": poc_volume,
            "poc_trade_count": None,  # K 线近似无法得到笔数
            "total_volume": total_volume,
            "poc_volume_ratio": (poc_volume / total_volume) if total_volume > 0 else None,
        }

    def calculate(self) -> Dict:
        """
        支撑 / 压力 / 密集区价格：始终按「本周期 K 线」结构计算，
        避免各周期共用近期逐笔时（尤其整点后）算出几乎一样的价位。

        若有逐笔，则额外统计落在该密集区价格桶内的成交量与笔数，便于推送展示。
        """
        profile = self.from_klines()
        if profile.get("poc") is None:
            # 无 K 线时再退回逐笔
            if self.trades:
                return self.from_trades(self.trades)
            return profile

        if self.trades:
            stats = self._trade_stats_at_poc(
                profile["poc"],
                profile.get("value_area_low"),
                profile.get("value_area_high"),
            )
            if stats["poc_volume"] is not None:
                profile["poc_volume"] = stats["poc_volume"]
            profile["poc_trade_count"] = stats["poc_trade_count"]
            if stats["total_volume"] is not None:
                profile["total_volume"] = stats["total_volume"]
                if profile["poc_volume"] and stats["total_volume"] > 0:
                    profile["poc_volume_ratio"] = (
                        profile["poc_volume"] / stats["total_volume"]
                    )
        return profile

    def _trade_stats_at_poc(
        self,
        poc: float,
        value_area_low: float | None,
        value_area_high: float | None,
    ) -> Dict:
        """统计当前缓冲成交里，落在密集区附近的量与笔数。"""
        if not self.trades or poc is None:
            return {
                "poc_volume": None,
                "poc_trade_count": None,
                "total_volume": None,
            }

        prices = np.array([t["price"] for t in self.trades], dtype=float)
        volumes = np.array([t["amount"] for t in self.trades], dtype=float)
        total_volume = float(volumes.sum())

        # 优先用 Value Area 作为「密集区」范围；否则用 POC 附近相对带宽
        low = value_area_low if value_area_low is not None else poc * 0.999
        high = value_area_high if value_area_high is not None else poc * 1.001
        if high < low:
            low, high = high, low

        mask = (prices >= low) & (prices <= high)
        if not np.any(mask):
            # 回退：距离 POC 最近的若干成交
            dist = np.abs(prices - poc)
            nearest = dist <= max(poc * 0.0005, 1e-8)
            mask = nearest

        return {
            "poc_volume": float(volumes[mask].sum()) if np.any(mask) else 0.0,
            "poc_trade_count": int(np.count_nonzero(mask)),
            "total_volume": total_volume,
        }
