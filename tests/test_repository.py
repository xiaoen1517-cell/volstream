import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config import get_db_url
from src.db.base import Base
from src.db.repository import AnalysisRepository, KlineRepository

DB_URL = get_db_url()
engine = create_engine(DB_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

skip_if_no_db = pytest.mark.skipif(
    os.getenv("SKIP_DB_TESTS", "1") == "1",
    reason="需要 PostgreSQL/TimescaleDB 环境，设置 SKIP_DB_TESTS=0 启用",
)


@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@skip_if_no_db
def test_save_and_get_klines(db_session):
    repo = KlineRepository()
    klines = [
        [1704067200000, 100.0, 101.0, 99.0, 100.5, 1000.0, 100500.0],
        [1704070800000, 100.5, 102.0, 100.0, 101.5, 1200.0, 121800.0],
    ]
    count = repo.save_klines("BTC/USDT", "binance", "1h", klines)
    assert count == 2

    df = repo.get_latest_klines("BTC/USDT", "binance", "1h", limit=10)
    assert len(df) == 2
    assert df.iloc[-1]["close"] == 101.5


@skip_if_no_db
def test_save_analysis(db_session):
    repo = AnalysisRepository()
    from datetime import datetime, timezone

    result = {
        "time": datetime.now(timezone.utc),
        "symbol": "BTC/USDT",
        "exchange": "binance",
        "timeframe": "15m",
        "ema_12": 100.0,
        "ema_26": 99.0,
        "signal": "Bullish",
        "signal_strength": 55.0,
        "reason": "test",
    }
    repo.save(result)
    df = repo.get_latest("BTC/USDT", "binance", ["15m"])
    assert len(df) == 1
    assert df.iloc[0]["signal"] == "Bullish"
