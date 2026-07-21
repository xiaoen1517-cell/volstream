from src.analytics.volume_profile import VolumeProfile


def test_volume_profile_from_trades():
    trades = [
        {"price": 100.0, "amount": 1.0, "quote_amount": 100.0},
        {"price": 100.1, "amount": 2.0, "quote_amount": 200.2},
        {"price": 100.2, "amount": 5.0, "quote_amount": 501.0},
        {"price": 100.3, "amount": 1.0, "quote_amount": 100.3},
    ]
    vp = VolumeProfile(trades=trades)
    result = vp.calculate()
    assert result["poc"] is not None
    assert result["value_area_high"] is not None
    assert result["value_area_low"] is not None
    assert result["value_area_low"] <= result["poc"] <= result["value_area_high"]
    assert result["poc_volume"] is not None and result["poc_volume"] > 0
    assert result["poc_trade_count"] is not None and result["poc_trade_count"] >= 1
    assert result["total_volume"] == 9.0


def test_volume_profile_prefers_klines_for_levels():
    """有成交时，支撑/压力仍应由本周期 K 线决定，而不是短窗口逐笔。"""
    import pandas as pd

    df = pd.DataFrame(
        {
            "high": [110, 120, 130, 125],
            "low": [100, 105, 115, 110],
            "close": [105, 118, 128, 120],
            "volume": [10.0, 20.0, 50.0, 15.0],
        }
    )
    # 逐笔全挤在很窄的区间，若误用 from_trades，支撑压力会几乎一样
    trades = [
        {"price": 119.0, "amount": 1.0},
        {"price": 119.1, "amount": 2.0},
        {"price": 119.2, "amount": 5.0},
    ]
    vp = VolumeProfile(df=df, trades=trades)
    result = vp.calculate()
    kline_only = VolumeProfile(df=df, trades=[]).from_klines()
    assert result["poc"] == kline_only["poc"]
    assert result["value_area_low"] == kline_only["value_area_low"]
    assert result["value_area_high"] == kline_only["value_area_high"]
    assert result["poc_trade_count"] is not None


def test_volume_profile_empty():
    vp = VolumeProfile(trades=[])
    result = vp.calculate()
    assert result["poc"] is None
    assert result["poc_volume"] is None
