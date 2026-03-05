from __future__ import annotations

from datetime import datetime
from typing import Iterable

import pandas as pd
from binance.client import Client


class BinanceDataFeed:
    def __init__(self, api_key: str | None, api_secret: str | None, timeout: int = 10):
        self.client = Client(api_key, api_secret, requests_params={"timeout": timeout})

    def fetch_candles(self, symbol: str, interval: str, limit: int = 300) -> pd.DataFrame:
        klines = self.client.get_klines(symbol=symbol, interval=interval, limit=limit)
        return self._to_dataframe(klines)

    @staticmethod
    def _to_dataframe(klines: Iterable[list]) -> pd.DataFrame:
        df = pd.DataFrame(
            klines,
            columns=[
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_asset_volume",
                "number_of_trades",
                "tbb",
                "tbq",
                "ignore",
            ],
        )
        df = df[["open_time", "open", "high", "low", "close", "volume"]]
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        numeric_cols = ["open", "high", "low", "close", "volume"]
        df[numeric_cols] = df[numeric_cols].astype(float)
        return df

    @staticmethod
    def latest_price(df: pd.DataFrame) -> float:
        if df.empty:
            raise ValueError("No price data available")
        return float(df.iloc[-1]["close"])

    @staticmethod
    def latest_timestamp(df: pd.DataFrame) -> datetime:
        if df.empty:
            raise ValueError("No timestamps available")
        return df.iloc[-1]["open_time"].to_pydatetime()
