import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Optional

import websockets

from src.config import CONFIG
from src.data.kline_store import KlineStore
from src.data.trade_buffer import TradeBuffer
from src.db.repository import KlineRepository
from src.signals.aggregate import SignalAggregator
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _load_proxy():
    """读取环境变量或配置文件中的 WebSocket 代理。"""
    proxy_url = os.getenv("WS_PROXY") or CONFIG.get("websocket", {}).get("proxy", "")
    if not proxy_url:
        return None
    try:
        from aiohttp_socks import ProxyConnector
        return ProxyConnector.from_url(proxy_url)
    except ImportError:
        logger.warning("aiohttp-socks 未安装，无法使用代理")
        return None


class ExchangeWebSocketClient:
    BINANCE_WS = "wss://stream.binance.com:9443/stream?streams={streams}"
    OKX_WS = "wss://ws.okx.com:8443/ws/v5/public"

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.exchange_name = CONFIG["exchange"]["name"]
        self.kline_store = KlineStore()
        self.trade_buffer = TradeBuffer()
        self.kline_repo = KlineRepository()
        self.aggregator = SignalAggregator(symbol, self.exchange_name)

    def _normalize_symbol(self) -> str:
        return self.symbol.replace("/", "").lower()

    def _build_streams(self) -> str:
        normalized = self._normalize_symbol()
        streams = [f"{normalized}@kline_{tf}" for tf in CONFIG["timeframes"]]
        streams.append(f"{normalized}@aggTrade")
        return "/".join(streams)

    def _build_url(self) -> str:
        if self.exchange_name == "binance":
            return self.BINANCE_WS.format(streams=self._build_streams())
        raise NotImplementedError(f"WebSocket for {self.exchange_name} not implemented")

    def _ws_timeout(self, key: str, default: int) -> int:
        env_val = os.getenv(f"WS_{key.upper()}_TIMEOUT")
        if env_val:
            return int(env_val)
        return int(CONFIG.get("websocket", {}).get(key, default))

    async def _process_message(self, msg: dict):
        stream = msg.get("stream", "")
        data = msg.get("data", {})

        if "@kline_" in stream:
            timeframe = stream.split("@kline_")[-1]
            k = data["k"]
            kline = {
                "time": datetime.fromtimestamp(k["t"] / 1000, tz=timezone.utc),
                "open": float(k["o"]),
                "high": float(k["h"]),
                "low": float(k["l"]),
                "close": float(k["c"]),
                "volume": float(k["v"]),
                "quote_volume": float(k["q"]),
                "is_closed": k["x"],
            }
            closed = self.kline_store.update(timeframe, kline)
            if closed:
                logger.info(f"{self.symbol} {timeframe} K 线闭合，开始分析...")
                self.kline_repo.save_klines(
                    self.symbol, self.exchange_name, timeframe, [
                        [
                            int(k["t"]), k["o"], k["h"], k["l"], k["c"], k["v"], k["q"]
                        ]
                    ]
                )
                trades = self.trade_buffer.flush(timeframe)
                await self.aggregator.analyze(timeframe, kline, trades)

        elif "@aggTrade" in stream:
            trade = {
                "time": datetime.fromtimestamp(data["T"] / 1000, tz=timezone.utc),
                "price": float(data["p"]),
                "amount": float(data["q"]),
                "quote_amount": float(data["p"]) * float(data["q"]),
                "is_buyer_maker": data["m"],
                "trade_id": str(data["a"]),
            }
            for tf in CONFIG["timeframes"]:
                self.trade_buffer.add(tf, trade)

    async def run(self):
        url = self._build_url()
        proxy = _load_proxy()
        open_timeout = self._ws_timeout("open", 30)
        ping_timeout = self._ws_timeout("ping", 20)
        close_timeout = self._ws_timeout("close", 10)

        logger.info(
            f"连接 WebSocket: {url} | proxy={'yes' if proxy else 'no'} | "
            f"open_timeout={open_timeout}s"
        )
        while True:
            try:
                connect_kwargs = {
                    "open_timeout": open_timeout,
                    "ping_timeout": ping_timeout,
                    "close_timeout": close_timeout,
                }
                if proxy:
                    connect_kwargs["proxy"] = proxy

                async with websockets.connect(url, **connect_kwargs) as ws:
                    async for message in ws:
                        await self._process_message(json.loads(message))
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket 断开: {e}，5 秒后重连...")
                await asyncio.sleep(5)
            except TimeoutError as e:
                logger.error(f"WebSocket 连接超时: {e}，10 秒后重连...")
                await asyncio.sleep(10)
            except Exception as e:
                logger.error(f"WebSocket 异常: {e}", exc_info=True)
                await asyncio.sleep(5)


async def run_websocket(symbol: str):
    client = ExchangeWebSocketClient(symbol)
    await client.run()
