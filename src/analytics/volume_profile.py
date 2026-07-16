from typing import Dict, List

import numpy as np
import pandas as pd

from src.config import CONFIG


class VolumeProfile:
    def __init__(self, df: pd.DataFrame = None, trades: List[dict] = None):
        self.df = df
        self.trades = trades or []
        self.cfg = CONFIG["analytics"]

    def from_trades(self, trades: List[dict]) -> Dict:
        """基于逐笔成交计算 Volume Profile。"""
        if not trades:
            return {"poc": None, "value_area_high": None, "value_area_low": None}

        prices = np.array([t["price"] for t in trades])
        volumes = np.array([t["amount"] for t in trades])

        bins = self.cfg["volume_profile_bins"]
        hist, bin_edges = np.histogram(prices, bins=bins, weights=volumes)
        max_idx = int(np.argmax(hist))
        poc = (bin_edges[max_idx] + bin_edges[max_idx + 1]) / 2

        total_volume = volumes.sum()
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
        }

    def from_klines(self) -> Dict:
        """基于 K 线数据近似计算 Volume Profile（备用）。"""
        if self.df is None or self.df.empty:
            return {"poc": None, "value_area_high": None, "value_area_low": None}

        # 用典型价格与成交量近似
        typical = (self.df["high"] + self.df["low"] + self.df["close"]) / 3
        bins = self.cfg["volume_profile_bins"]
        hist, bin_edges = np.histogram(typical, bins=bins, weights=self.df["volume"])
        max_idx = int(np.argmax(hist))
        poc = (bin_edges[max_idx] + bin_edges[max_idx + 1]) / 2

        total_volume = self.df["volume"].sum()
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
        }

    def calculate(self) -> Dict:
        if self.trades:
            return self.from_trades(self.trades)
        return self.from_klines()
