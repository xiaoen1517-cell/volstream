import asyncio
import json
from datetime import datetime, timezone

import websockets

from src.config import CONFIG
from src.data.kline_store import KlineStore
from src.data.trade_buffer import TradeBuffer
from src.db.repository import KlineRepository
from src.signals.aggregate import SignalAggregator
from src.utils.logger import get_logger

logger = get_logger(__name__)


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
        logger.info(f"连接 WebSocket: {url}")
        while True:
            try:
                async with websockets.connect(url) as ws:
                    async for message in ws:
                        await self._process_message(json.loads(message))
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket 断开: {e}，5 秒后重连...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"WebSocket 异常: {e}", exc_info=True)
                await asyncio.sleep(5)


async def run_websocket(symbol: str):
    client = ExchangeWebSocketClient(symbol)
    await client.run()
