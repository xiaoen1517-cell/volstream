import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import ccxt

from src.config import CONFIG


class ExchangeClient:
    def __init__(self, exchange_name: Optional[str] = None):
        self.exchange_name = exchange_name or CONFIG["exchange"]["name"]
        self._init_exchange()

    def _init_exchange(self):
        api_key = os.getenv(f"{self.exchange_name.upper()}_API_KEY") or None
        secret = os.getenv(f"{self.exchange_name.upper()}_SECRET") or None
        password = os.getenv(f"{self.exchange_name.upper()}_PASSWORD") or None

        config = {
            "enableRateLimit": CONFIG["exchange"].get("enableRateLimit", True),
            "options": {"defaultType": "spot"},
        }
        if api_key and secret:
            config["apiKey"] = api_key
            config["secret"] = secret
            if password:
                config["password"] = password

        exchange_class = getattr(ccxt, self.exchange_name)
        self.exchange = exchange_class(config)
        if CONFIG["exchange"].get("sandbox"):
            self.exchange.set_sandbox_mode(True)

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        days: int = 30,
        limit: int = 1000,
    ) -> List[List]:
        since = int(
            (datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000
        )
        all_klines = []
        while True:
            klines = self.exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            if not klines:
                break
            all_klines.extend(klines)
            since = klines[-1][0] + 1
            if len(klines) < limit:
                break
        return all_klines
