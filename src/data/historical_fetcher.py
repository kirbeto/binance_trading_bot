from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

import pandas as pd
from binance.client import Client


class HistoricalFetcher:
    def __init__(self, api_key: str | None = None, api_secret: str | None = None, data_dir: str = "data"):
        self.client = Client(api_key, api_secret)
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def fetch_klines(self, symbol: str, interval: Literal["15m", "1h"], limit: int = 1000) -> Path:
        klines = self.client.get_klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(klines, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "tbb", "tbq", "ignore"
        ])
        df = df[["open_time", "open", "high", "low", "close", "volume"]]
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)

        out_path = self.data_dir / f"{symbol}_{interval}_{datetime.utcnow():%Y%m%d%H%M%S}.csv"
        df.to_csv(out_path, index=False)
        return out_path
