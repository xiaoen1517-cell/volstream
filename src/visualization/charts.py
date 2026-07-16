from typing import Dict, Optional

import matplotlib.pyplot as plt
import pandas as pd


class ChartRenderer:
    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()
        self.df.sort_values("time", inplace=True)

    def plot_analysis(self, profile: Optional[Dict] = None, save_path: Optional[str] = None):
        """绘制 K 线、均线、成交量与 Volume Profile 标记。"""
        fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True,
                                  gridspec_kw={"height_ratios": [3, 1, 1]})

        ax_price = axes[0]
        ax_vol = axes[1]
        ax_obv = axes[2]

        # 价格与均线
        ax_price.plot(self.df["time"], self.df["close"], label="Close", linewidth=1.5)
        if "ema_12" in self.df.columns:
            ax_price.plot(self.df["time"], self.df["ema_12"], label="EMA12", alpha=0.8)
        if "ema_26" in self.df.columns:
            ax_price.plot(self.df["time"], self.df["ema_26"], label="EMA26", alpha=0.8)
        if "vwap" in self.df.columns:
            ax_price.plot(self.df["time"], self.df["vwap"], label="VWAP", alpha=0.7)

        if profile:
            poc = profile.get("poc")
            vah = profile.get("value_area_high")
            val = profile.get("value_area_low")
            if poc:
                ax_price.axhline(poc, color="purple", linestyle="--", label=f"POC {poc:.2f}")
            if vah:
                ax_price.axhline(vah, color="green", linestyle=":", alpha=0.6, label="VAH")
            if val:
                ax_price.axhline(val, color="red", linestyle=":", alpha=0.6, label="VAL")

        ax_price.set_title("Price & Indicators")
        ax_price.legend(loc="upper left")
        ax_price.grid(True, alpha=0.3)

        # 成交量
        colors = ["green" if c >= o else "red" for c, o in zip(self.df["close"], self.df["open"])]
        ax_vol.bar(self.df["time"], self.df["volume"], color=colors, alpha=0.7)
        ax_vol.set_ylabel("Volume")
        ax_vol.grid(True, alpha=0.3)

        # OBV / Delta
        if "obv" in self.df.columns:
            ax_obv.plot(self.df["time"], self.df["obv"], label="OBV", color="blue")
            ax_obv.set_ylabel("OBV")
        ax_obv.grid(True, alpha=0.3)

        plt.tight_layout()
        if save_path:
            plt.savefig(save_path, dpi=150)
        else:
            plt.show()
