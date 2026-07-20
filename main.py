#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

import click
from rich.console import Console
from rich.table import Table

from src.config import CONFIG

console = Console()


@click.group()
def cli():
    """VolStream CLI"""
    pass


@cli.command()
def init_db():
    """初始化数据库表与 hypertable"""
    from src.db.base import init_database

    init_database()
    console.print("[green]数据库初始化完成[/green]")


@cli.command()
@click.option("--symbol", default=None, help="交易对，例如 BTC/USDT；省略则同步 config 中全部 symbols")
@click.option("--days", default=None, type=int, help="同步天数，默认读取配置")
def sync(symbol: Optional[str], days: Optional[int]):
    """同步历史 K 线到数据库（显式全量拉取，不跳过）"""
    from src.exchange.client import ExchangeClient
    from src.db.repository import KlineRepository

    days = days or CONFIG["app"]["history_days"]
    symbols = [symbol] if symbol else list(CONFIG["symbols"])
    client = ExchangeClient()
    repo = KlineRepository()

    for sym in symbols:
        for timeframe in CONFIG["timeframes"]:
            console.print(f"[cyan]同步 {sym} {timeframe} 最近 {days} 天数据...[/cyan]")
            klines = client.fetch_ohlcv(sym, timeframe, days=days)
            repo.save_klines(sym, client.exchange_name, timeframe, klines)
            console.print(f"[green]写入 {len(klines)} 条 {sym} {timeframe} K 线[/green]")


@cli.command()
@click.option("--symbol", default="BTC/USDT", help="交易对")
@click.option("--timeframe", default="15m", help="周期")
@click.option("--limit", default=100, help="分析最近 N 根 K 线")
def analyze(symbol: str, timeframe: str, limit: int):
    """离线分析最近 N 根 K 线"""
    from src.db.repository import KlineRepository
    from src.indicators.price_volume import calculate_all
    from src.analytics.volume_profile import VolumeProfile

    repo = KlineRepository()
    df = repo.get_latest_klines(symbol, CONFIG["exchange"]["name"], timeframe, limit=limit)
    if df.empty:
        console.print("[red]数据库中无数据，请先执行 sync[/red]")
        return

    df = calculate_all(df)
    vp = VolumeProfile(df)
    profile = vp.calculate()

    table = Table(title=f"{symbol} {timeframe} 分析结果")
    table.add_column("指标", justify="right")
    table.add_column("数值")

    table.add_row("Close", f"{df['close'].iloc[-1]:.2f}")
    table.add_row("EMA12", f"{df['ema_12'].iloc[-1]:.2f}")
    table.add_row("EMA26", f"{df['ema_26'].iloc[-1]:.2f}")
    table.add_row("RSI14", f"{df['rsi'].iloc[-1]:.2f}")
    table.add_row("VWAP", f"{df['vwap'].iloc[-1]:.2f}")
    table.add_row("ATR", f"{df['atr'].iloc[-1]:.2f}")
    table.add_row("POC", f"{profile.get('poc', float('nan')):.2f}")
    table.add_row("Value Area High", f"{profile.get('value_area_high', float('nan')):.2f}")
    table.add_row("Value Area Low", f"{profile.get('value_area_low', float('nan')):.2f}")

    console.print(table)


@cli.command()
@click.option("--symbol", default=None, help="交易对；省略则并发跑 config 中全部 symbols")
def run(symbol: Optional[str]):
    """启动 WebSocket 实时分析"""
    from src.exchange.websocket_client import run_websocket

    asyncio.run(run_websocket(symbol))


@cli.command()
def cleanup():
    """清理 30 天前的历史数据"""
    from src.db.repository import KlineRepository, AnalysisRepository

    days = CONFIG["app"]["history_days"]
    KlineRepository().cleanup_old_data(days)
    AnalysisRepository().cleanup_old_data(days)
    console.print(f"[green]已清理 {days} 天前的数据[/green]")


if __name__ == "__main__":
    cli()
