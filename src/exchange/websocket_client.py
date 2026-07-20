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
        """解析 K 线数据，返回统一格式或 None。"""
        raise NotImplementedError

    @abstractmethod
    def parse_trades(self, data: Any) -> List[Dict[str, Any]]:
        """解析成交数据，返回统一格式列表。"""
        raise NotImplementedError

    @abstractmethod
    def get_timeframe_from_message(self, msg: Dict[str, Any]) -> Optional[str]:
        raise NotImplementedError

    async def _on_kline_closed(self, timeframe: str, kline: Dict[str, Any]):
        from src.utils.exchange_time import format_kline_period

        tf_cn = {"5m": "5分钟", "15m": "15分钟", "1h": "1小时", "4h": "4小时"}.get(
            timeframe, timeframe
        )
        period = format_kline_period(kline, timeframe)
        logger.info(f"【{self.symbol} · {tf_cn}】交易所K线 {period} 已收盘，开始分析…")
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

        # 非 5m：只更新本周期（收盘成交更完整）；共振统一由 5m 触发
        if timeframe != "5m":
            await self.aggregator.analyze(
                timeframe, kline, trades, emit_resonance=False
            )
            return

        # 5m：重算四个周期指标后再共振，避免大周期丢掉刚收的这根 5m
        higher_trades = {
            tf: self.trade_buffer.peek(tf)
            for tf in CONFIG["timeframes"]
            if tf != "5m"
        }
        await self.aggregator.on_5m_close(kline, trades, higher_trades)

    async def _process_message(self, msg: Dict[str, Any]):
        tf = self.get_timeframe_from_message(msg)
        if tf:
            raw = msg.get("data")
            if raw is None:
                return
            kline = self.parse_kline(raw)
            if not kline:
                return
            if kline.get("close_timestamp_ms") is None:
                from src.utils.exchange_time import resolve_close_ms

                kline["close_timestamp_ms"] = resolve_close_ms(
                    int(kline["timestamp_ms"]), tf
                )
            closed = self.kline_store.update(tf, kline)
            if closed:
                await self._on_kline_closed(tf, kline)
            return

        raw = msg.get("data")
        if raw is None:
            return
        trades = self.parse_trades(raw)
        for trade in trades:
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
        # Binance 组合流 data 是单条事件 dict，不是数组
        if not isinstance(data, dict):
            return None
        k = data.get("k", data)
        if not isinstance(k, dict) or "t" not in k:
            return None
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
            "close_timestamp_ms": int(k["T"]) if k.get("T") is not None else None,
        }

    def parse_trades(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(data, dict) or "T" not in data:
            return []
        trade = {
            "time": datetime.fromtimestamp(data["T"] / 1000, tz=timezone.utc),
            "price": float(data["p"]),
            "amount": float(data["q"]),
            "quote_amount": float(data["p"]) * float(data["q"]),
            "is_buyer_maker": data.get("m", False),
            "trade_id": str(data.get("a", "")),
        }
        return [trade]

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
        if not isinstance(data, list) or not data:
            return None
        # OKX candle 字段顺序: ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm
        item = data[-1]
        if not isinstance(item, list) or len(item) < 9:
            return None
        ts = int(item[0])
        return {
            "time": datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[5]),
            "quote_volume": float(item[6]) if item[6] else 0.0,
            "is_closed": bool(int(item[8])) if len(item) > 8 else False,
            "timestamp_ms": ts,
            "close_timestamp_ms": None,
        }

    def parse_trades(self, data: List[Any]) -> List[Dict[str, Any]]:
        if not isinstance(data, list):
            return []
        trades = []
        for item in data:
            side = item.get("side", "buy")
            trades.append({
                "time": datetime.fromtimestamp(int(item["ts"]) / 1000, tz=timezone.utc),
                "price": float(item["px"]),
                "amount": float(item["sz"]),
                "quote_amount": float(item["px"]) * float(item["sz"]),
                "is_buyer_maker": side == "sell",
                "trade_id": str(item.get("tradeId", "")),
            })
        return trades

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


async def bootstrap_analysis(symbols: List[str]) -> None:
    """启动前为各币种四周期用历史 K 线打底，避免新币种等不到 4h 收盘。"""
    exchange = CONFIG["exchange"]["name"]
    logger.info(f"开始历史分析打底: {', '.join(symbols)}")
    for symbol in symbols:
        aggregator = SignalAggregator(symbol, exchange)
        count = await aggregator.bootstrap_from_klines()
        logger.info(f"【{symbol}】打底完成，已覆盖 {count}/{len(CONFIG['timeframes'])} 个周期")


async def ensure_startup_data(symbols: List[str]) -> None:
    """启动检查：历史 K 线不足则补全，再做分析打底。"""
    from src.data.history import ensure_history

    # 拉取为同步 IO，放到线程池以免卡住事件循环过久（虽此时尚未连 WS）
    await asyncio.to_thread(ensure_history, symbols)
    await bootstrap_analysis(symbols)


async def run_websocket(symbol: Optional[str] = None):
    """启动 WebSocket；未指定 symbol 时并发跑 CONFIG['symbols'] 全部交易对。"""
    symbols = [symbol] if symbol else list(CONFIG["symbols"])
    if not symbols:
        raise ValueError("未指定交易对，且 config.yaml 中 symbols 为空")

    await ensure_startup_data(symbols)

    logger.info(f"启动 WebSocket 实时分析: {', '.join(symbols)}")
    clients = [create_client(s) for s in symbols]
    await asyncio.gather(*(c.run() for c in clients))
