from src.analytics.whale_detector import WhaleDetector


def test_whale_detection():
    trades = [
        {"price": 100, "amount": 1000, "quote_amount": 100000, "is_buyer_maker": False},
        {"price": 100, "amount": 10, "quote_amount": 1000, "is_buyer_maker": True},
        {"price": 99, "amount": 600, "quote_amount": 59400, "is_buyer_maker": True},
    ]
    detector = WhaleDetector(threshold_usd=50000)
    result = detector.analyze(trades)
    assert result["whale_buy_count"] == 1
    assert result["whale_sell_count"] == 1
    assert result["whale_buy_ratio"] > 0
    assert result["whale_sell_ratio"] > 0


def test_no_whales():
    trades = [
        {"price": 100, "amount": 0.1, "quote_amount": 10, "is_buyer_maker": False},
    ]
    detector = WhaleDetector(threshold_usd=50000)
    result = detector.analyze(trades)
    assert result["whale_buy_count"] == 0
    assert result["whale_sell_count"] == 0
