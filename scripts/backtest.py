"""Phase 3 backtest runner."""

import pandas as pd
from rich.console import Console

from src.signals.trend_signal import TrendSignalGenerator
from src.backtest.engine import BacktestEngine

console = Console()

SETTINGS = {
    "ema_fast": 50,
    "ema_slow": 200,
    "rsi_period": 14,
    "rsi_min": 40,
    "rsi_max": 60,
}

def main():
    df = pd.read_csv("data/sample_backtest.csv")
    generator = TrendSignalGenerator()
    engine = BacktestEngine(capital=80, tp_pct=0.015, sl_pct=0.0075, risk_pct=0.02, max_consecutive_losses=3)
    metrics = engine.run(df, generator, SETTINGS)
    console.log(metrics)


if __name__ == "__main__":
    main()
