import pandas as pd
import pytest

from src.indicators.price_volume import calculate_all


def _make_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=50, freq="h"),
            "open": [100 + i * 0.1 for i in range(50)],
            "high": [101 + i * 0.1 for i in range(50)],
            "low": [99 + i * 0.1 for i in range(50)],
            "close": [100.5 + i * 0.1 for i in range(50)],
            "volume": [10 + i for i in range(50)],
        }
    )


def test_calculate_all_columns():
    df = _make_df()
    result = calculate_all(df)
    expected = {"ema_12", "ema_26", "macd", "macd_signal", "rsi", "vwap", "obv", "delta", "cvd", "atr"}
    assert expected.issubset(set(result.columns))


def test_ema_values():
    df = _make_df()
    result = calculate_all(df)
    assert result["ema_12"].iloc[-1] > 0
    assert result["ema_26"].iloc[-1] > 0


def test_rsi_range():
    df = _make_df()
    result = calculate_all(df)
    valid = result["rsi"].dropna()
    assert ((valid >= 0) & (valid <= 100)).all()
