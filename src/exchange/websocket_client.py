import asyncio
import json
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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


def _ws_timeout(key: str, default: int) -> int:
    env_val = os.getenv(f"WS_{key.upper()}_TIMEOUT")
    if env_val:
        return int(env_val)
    return int(CONFIG.get("websocket", {}).get(key, default))


class ExchangeWebSocketClient(ABC):
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.exchange_name = CONFIG["exchange"]["name"]
        self.kline_store = KlineStore()
        self.trade_buffer = TradeBuffer()
        self.kline_repo = KlineRepository()
        self.aggregator = SignalAggregator(symbol, self.exchange_name)

    @abstractmethod
    def build_url(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def build_subscribe_messages(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def parse_kline(self, data: Any) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def parse_trade(self, data: Any) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_timeframe_from_message(self, msg: Dict[str, Any]) -> Optional[str]:
        raise NotImplementedError

    async def _on_kline_closed(self, timeframe: str, kline: Dict[str, Any]):
        logger.info(f"{self.symbol} {timeframe} K 线闭合，开始分析...")
        self.kline_repo.save_klines(
            self.symbol, self.exchange_name, timeframe, [
                [
                    int(kline["timestamp_ms"]),
                    kline["open"],
                    kline["high"],
                    kline["low"],
                    kline["close"],
                    kline["volume"],
                    kline["quote_volume"],
                ]
            ]
        )
        trades = self.trade_buffer.flush(timeframe)
        await self.aggregator.analyze(timeframe, kline, trades)

    async def _process_message(self, msg: Dict[str, Any]):
        tf = self.get_timeframe_from_message(msg)
        if tf:
            data_list = msg.get("data", [])
            if not data_list:
                return
            # OKX/Binance 推送的都是数组，取最后一条（最新状态）
            kline = self.parse_kline(data_list[-1])
            if not kline:
                return
            closed = self.kline_store.update(tf, kline)
            if closed:
                await self._on_kline_closed(tf, kline)
            return

        trade_data = msg.get("data")
        if trade_data:
            # Binance 单条，OKX 数组
            items = trade_data if isinstance(trade_data, list) else [trade_data]
            for item in items:
                trade = self.parse_trade(item)
                if trade:
                    for tf in CONFIG["timeframes"]:
                        self.trade_buffer.add(tf, trade)

    async def run(self):
        url = self.build_url()
        proxy = _load_proxy()
        open_timeout = _ws_timeout("open", 30)
        ping_timeout = _ws_timeout("ping", 20)
        close_timeout = _ws_timeout("close", 10)

        logger.info(
            f"连接 WebSocket: {url} | exchange={self.exchange_name} | "
            f"proxy={'yes' if proxy else 'no'} | open_timeout={open_timeout}s"
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
                    for sub in self.build_subscribe_messages():
                        await ws.send(json.dumps(sub))

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


class BinanceWebSocketClient(ExchangeWebSocketClient):
    WS_URL = "wss://stream.binance.com:9443/stream?streams={streams}"

    def build_url(self) -> str:
        normalized = self.symbol.replace("/", "").lower()
        streams = [f"{normalized}@kline_{tf}" for tf in CONFIG["timeframes"]]
        streams.append(f"{normalized}@aggTrade")
        return self.WS_URL.format(streams="/".join(streams))

    def build_subscribe_messages(self) -> List[Dict[str, Any]]:
        return []

    def parse_kline(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        k = data.get("k", data)
        return {
            "time": datetime.fromtimestamp(k["t"] / 1000, tz=timezone.utc),
            "open": float(k["o"]),
            "high": float(k["h"]),
            "low": float(k["l"]),
            "close": float(k["c"]),
            "volume": float(k["v"]),
            "quote_volume": float(k["q"]),
            "is_closed": k["x"],
            "timestamp_ms": int(k["t"]),
        }

    def parse_trade(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return {
            "time": datetime.fromtimestamp(data["T"] / 1000, tz=timezone.utc),
            "price": float(data["p"]),
            "amount": float(data["q"]),
            "quote_amount": float(data["p"]) * float(data["q"]),
            "is_buyer_maker": data.get("m", False),
            "trade_id": str(data.get("a", "")),
        }

    def get_timeframe_from_message(self, msg: Dict[str, Any]) -> Optional[str]:
        stream = msg.get("stream", "")
        if "@kline_" in stream:
            return stream.split("@kline_")[-1]
        return None


class OkxWebSocketClient(ExchangeWebSocketClient):
    WS_URL = "wss://ws.okx.com:8443/ws/v5/public"

    def _inst_id(self) -> str:
        return self.symbol.replace("/", "-")

    def build_url(self) -> str:
        return self.WS_URL

    def build_subscribe_messages(self) -> List[Dict[str, Any]]:
        inst_id = self._inst_id()
        args = []
        for tf in CONFIG["timeframes"]:
            args.append({"channel": f"candle{tf}", "instId": inst_id})
        args.append({"channel": "trades", "instId": inst_id})
        return [{"op": "subscribe", "args": args}]

    def parse_kline(self, data: List[Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(data, list) or len(data) < 9:
            return None
        # OKX candle 字段顺序: ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm
        ts = int(data[0])
        return {
            "time": datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
            "open": float(data[1]),
            "high": float(data[2]),
            "low": float(data[3]),
            "close": float(data[4]),
            "volume": float(data[5]),
            "quote_volume": float(data[6]) if data[6] else 0.0,
            "is_closed": bool(int(data[8])) if len(data) > 8 else False,
            "timestamp_ms": ts,
        }

    def parse_trade(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        side = data.get("side", "buy")
        return {
            "time": datetime.fromtimestamp(int(data["ts"]) / 1000, tz=timezone.utc),
            "price": float(data["px"]),
            "amount": float(data["sz"]),
            "quote_amount": float(data["px"]) * float(data["sz"]),
            "is_buyer_maker": side == "sell",
            "trade_id": str(data.get("tradeId", "")),
        }

    def get_timeframe_from_message(self, msg: Dict[str, Any]) -> Optional[str]:
        arg = msg.get("arg", {})
        channel = arg.get("channel", "")
        if channel.startswith("candle"):
            return channel.replace("candle", "")
        return None


def create_client(symbol: str) -> ExchangeWebSocketClient:
    exchange = CONFIG["exchange"]["name"]
    if exchange == "binance":
        return BinanceWebSocketClient(symbol)
    if exchange == "okx":
        return OkxWebSocketClient(symbol)
    raise ValueError(f"Unsupported exchange: {exchange}")


async def run_websocket(symbol: str):
    client = create_client(symbol)
    await client.run()
