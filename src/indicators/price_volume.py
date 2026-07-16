import numpy as np
import pandas as pd

from src.config import CONFIG


def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    cfg = CONFIG["indicators"]
    df = df.copy()
    df.sort_values("time", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # EMA
    df["ema_12"] = df["close"].ewm(span=cfg["ema_short"], adjust=False).mean()
    df["ema_26"] = df["close"].ewm(span=cfg["ema_long"], adjust=False).mean()

    # MACD
    ema_fast = df["close"].ewm(span=cfg["macd_fast"], adjust=False).mean()
    ema_slow = df["close"].ewm(span=cfg["macd_slow"], adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=cfg["macd_signal"], adjust=False).mean()

    # RSI
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(com=cfg["rsi_period"] - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=cfg["rsi_period"] - 1, adjust=False).mean()
    rs = avg_gain / avg_loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # VWAP
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    df["vwap"] = (typical_price * df["volume"]).cumsum() / df["volume"].cumsum()

    # OBV
    df["obv"] = np.where(
        df["close"] > df["close"].shift(1),
        df["volume"],
        np.where(df["close"] < df["close"].shift(1), -df["volume"], 0),
    ).cumsum()

    # Delta / CVD (基于 K 线内价格方向近似)
    df["delta"] = np.where(
        df["close"] >= df["open"], df["volume"], -df["volume"]
    )
    df["cvd"] = df["delta"].cumsum()

    # ATR
    high_low = df["high"] - df["low"]
    high_close = np.abs(df["high"] - df["close"].shift())
    low_close = np.abs(df["low"] - df["close"].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.ewm(span=cfg["rsi_period"], adjust=False).mean()

    return df
