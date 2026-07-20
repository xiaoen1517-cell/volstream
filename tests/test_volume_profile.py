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


def test_volume_profile_empty():
    vp = VolumeProfile(trades=[])
    result = vp.calculate()
    assert result["poc"] is None
    assert result["poc_volume"] is None
