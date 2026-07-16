from src.analytics.iceberg_detector import IcebergDetector


def test_iceberg_detected():
    trades = []
    for i in range(25):
        trades.append(
            {
                "price": 100.0,
                "amount": 10.0,
                "quote_amount": 1000000.0,
                "is_buyer_maker": False,
            }
        )
    detector = IcebergDetector()
    result = detector.analyze(trades)
    assert result["iceberg_score"] > 0
    assert result["iceberg_level"] == 100.0
    assert result["iceberg_side"] == "buy"


def test_iceberg_not_enough_trades():
    trades = [
        {"price": 100.0, "amount": 10.0, "quote_amount": 1000000.0, "is_buyer_maker": False}
    ]
    detector = IcebergDetector()
    result = detector.analyze(trades)
    assert result["iceberg_score"] == 0.0
