"""Phase 2 signal generator CLI."""

import pandas as pd
from rich.console import Console

from src.data.historical_fetcher import HistoricalFetcher
from src.signals.trend_signal import TrendSignalGenerator

console = Console()

SETTINGS = {
    "ema_fast": 50,
    "ema_slow": 200,
    "rsi_period": 14,
    "rsi_min": 40,
    "rsi_max": 60,
}

def main():
    fetcher = HistoricalFetcher()
    latest_file = fetcher.fetch_klines("BTCUSDT", "15m")
    df = pd.read_csv(latest_file)

    generator = TrendSignalGenerator()
    result = generator.generate(df, **SETTINGS)

    console.log(f"Signal: {result.signal} | Reason: {result.reason} | Timestamp: {result.timestamp}")


if __name__ == "__main__":
    main()
