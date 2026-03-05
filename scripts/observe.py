"""Phase 1 observation CLI."""

from pathlib import Path

import pandas as pd
from rich.console import Console

from src.data.historical_fetcher import HistoricalFetcher
from src.indicators.ema import ema
from src.indicators.rsi import rsi
from src.state.market_state import classify_state

console = Console()

def main():
    fetcher = HistoricalFetcher()
    latest_file = fetcher.fetch_klines("BTCUSDT", "15m")
    df = pd.read_csv(latest_file)
    df["ema_50"] = ema(df["close"], 50)
    df["ema_200"] = ema(df["close"], 200)
    df["rsi_14"] = rsi(df["close"], 14)
    state = classify_state(df, 50, 200)
    console.log(f"Latest file: {Path(latest_file).name}")
    console.log(df.tail()[["open_time", "close", "ema_50", "ema_200", "rsi_14"]])
    console.log(f"Market state: {state}")


if __name__ == "__main__":
    main()
