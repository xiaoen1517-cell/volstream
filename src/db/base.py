from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import declarative_base, sessionmaker

from src.config import get_db_url

Base = declarative_base()
engine = create_engine(get_db_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_database():
    """创建所有表，并将时序表转换为 TimescaleDB hypertable。"""
    from src.db import models  # noqa: F401 — 注册表到 Base.metadata

    Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        # 将 klines 转换为 hypertable
        conn.execute(text("""
            SELECT create_hypertable('klines', 'time', if_not_exists => TRUE,
                                     chunk_time_interval => INTERVAL '1 day');
        """))
        # 将 analysis_results 转换为 hypertable
        conn.execute(text("""
            SELECT create_hypertable('analysis_results', 'time', if_not_exists => TRUE,
                                     chunk_time_interval => INTERVAL '1 day');
        """))
        # 将 whale_trades 转换为 hypertable
        conn.execute(text("""
            SELECT create_hypertable('whale_trades', 'time', if_not_exists => TRUE,
                                     chunk_time_interval => INTERVAL '1 day');
        """))
        conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
