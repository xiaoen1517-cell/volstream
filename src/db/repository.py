from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pandas as pd
from sqlalchemy import delete, insert, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.db.base import SessionLocal
from src.db.models import AnalysisResult, Kline, WhaleTrade


class KlineRepository:
    def save_klines(
        self,
        symbol: str,
        exchange: str,
        timeframe: str,
        klines: List[List],
    ) -> int:
        if not klines:
            return 0

        records = []
        for k in klines:
            ts = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
            records.append(
                {
                    "time": ts,
                    "symbol": symbol,
                    "exchange": exchange,
                    "timeframe": timeframe,
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "quote_volume": float(k[6]) if len(k) > 6 else None,
                }
            )

        stmt = pg_insert(Kline).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["time", "symbol", "exchange", "timeframe"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "quote_volume": stmt.excluded.quote_volume,
            },
        )

        with SessionLocal() as session:
            session.execute(stmt)
            session.commit()
        return len(records)

    def get_latest_klines(
        self,
        symbol: str,
        exchange: str,
        timeframe: str,
        limit: int = 100,
    ) -> pd.DataFrame:
        with SessionLocal() as session:
            rows = (
                session.query(Kline)
                .filter_by(symbol=symbol, exchange=exchange, timeframe=timeframe)
                .order_by(Kline.time.desc())
                .limit(limit)
                .all()
            )

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(
            [
                {
                    "time": r.time,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                    "quote_volume": r.quote_volume,
                }
                for r in rows
            ]
        )
        df = df.sort_values("time").reset_index(drop=True)
        return df

    def cleanup_old_data(self, days: int = 30) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with SessionLocal() as session:
            result = session.execute(
                delete(Kline).where(Kline.time < cutoff)
            )
            session.commit()
            return result.rowcount


class AnalysisRepository:
    def save(self, result: dict) -> None:
        with SessionLocal() as session:
            session.execute(
                pg_insert(AnalysisResult)
                .values(result)
                .on_conflict_do_update(
                    index_elements=["time", "symbol", "exchange", "timeframe"],
                    set_=result,
                )
            )
            session.commit()

    def get_latest(
        self,
        symbol: str,
        exchange: str,
        timeframes: List[str],
        limit: int = 1,
    ) -> pd.DataFrame:
        """每个 timeframe 各取最新 limit 条，避免短周期高频写入挤掉其它周期。"""
        rows = []
        with SessionLocal() as session:
            for tf in timeframes:
                tf_rows = (
                    session.query(AnalysisResult)
                    .filter_by(symbol=symbol, exchange=exchange, timeframe=tf)
                    .order_by(AnalysisResult.time.desc())
                    .limit(limit)
                    .all()
                )
                rows.extend(tf_rows)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(
            [
                {
                    "time": r.time,
                    "timeframe": r.timeframe,
                    "signal": r.signal,
                    "signal_strength": r.signal_strength,
                    "reason": r.reason,
                    "poc": r.poc,
                    "value_area_high": r.value_area_high,
                    "value_area_low": r.value_area_low,
                    "ema_12": r.ema_12,
                    "ema_26": r.ema_26,
                    "rsi": r.rsi,
                }
                for r in rows
            ]
        )
        return df.sort_values(["timeframe", "time"]).reset_index(drop=True)

    def cleanup_old_data(self, days: int = 30) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with SessionLocal() as session:
            result = session.execute(
                delete(AnalysisResult).where(AnalysisResult.time < cutoff)
            )
            session.commit()
            return result.rowcount


class WhaleTradeRepository:
    def save(self, trades: List[dict]) -> int:
        if not trades:
            return 0
        with SessionLocal() as session:
            session.execute(
                pg_insert(WhaleTrade)
                .values(trades)
                .on_conflict_do_nothing(
                    index_elements=["time", "symbol", "exchange", "trade_id"]
                )
            )
            session.commit()
        return len(trades)
