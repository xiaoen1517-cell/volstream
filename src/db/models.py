from sqlalchemy import Column, Double, PrimaryKeyConstraint, Text, DateTime
from sqlalchemy.sql import func

from src.db.base import Base


class Kline(Base):
    __tablename__ = "klines"
    __table_args__ = (
        PrimaryKeyConstraint("time", "symbol", "exchange", "timeframe"),
    )

    time = Column(DateTime(timezone=True), nullable=False)
    symbol = Column(Text, nullable=False)
    exchange = Column(Text, nullable=False)
    timeframe = Column(Text, nullable=False)
    open = Column(Double, nullable=False)
    high = Column(Double, nullable=False)
    low = Column(Double, nullable=False)
    close = Column(Double, nullable=False)
    volume = Column(Double, nullable=False)
    quote_volume = Column(Double, nullable=True)


class AnalysisResult(Base):
    __tablename__ = "analysis_results"
    __table_args__ = (
        PrimaryKeyConstraint("time", "symbol", "exchange", "timeframe"),
    )

    time = Column(DateTime(timezone=True), nullable=False)
    symbol = Column(Text, nullable=False)
    exchange = Column(Text, nullable=False)
    timeframe = Column(Text, nullable=False)

    ema_12 = Column(Double)
    ema_26 = Column(Double)
    macd = Column(Double)
    macd_signal = Column(Double)
    rsi = Column(Double)
    vwap = Column(Double)
    obv = Column(Double)
    delta = Column(Double)
    cvd = Column(Double)
    atr = Column(Double)

    poc = Column(Double)
    value_area_high = Column(Double)
    value_area_low = Column(Double)
    poc_volume = Column(Double)
    poc_trade_count = Column(Double)

    whale_buy_ratio = Column(Double)
    whale_sell_ratio = Column(Double)
    iceberg_score = Column(Double)

    signal = Column(Text)
    signal_strength = Column(Double)
    reason = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class WhaleTrade(Base):
    __tablename__ = "whale_trades"
    __table_args__ = (
        PrimaryKeyConstraint("time", "symbol", "exchange", "trade_id"),
    )

    time = Column(DateTime(timezone=True), nullable=False)
    symbol = Column(Text, nullable=False)
    exchange = Column(Text, nullable=False)
    trade_id = Column(Text, nullable=False)
    price = Column(Double, nullable=False)
    amount = Column(Double, nullable=False)
    quote_amount = Column(Double, nullable=False)
    side = Column(Text, nullable=False)  # buy | sell
