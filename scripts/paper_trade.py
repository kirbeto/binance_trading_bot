"""Run a configured bot in paper-trading mode."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_settings
from src.data.binance_feed import BinanceDataFeed
from src.execution.paper import PaperTrader
from src.execution.state import AccountStateStore
from src.risk.manager import RiskManager
from src.strategy import build_strategy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Binance multi-profile paper trader")
    parser.add_argument("--config", default="config/bot.yaml", help="Path to YAML config")
    parser.add_argument("--loop", action="store_true", help="Continuously run with configured interval")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    console = Console()
    settings = load_settings(args.config)

    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")

    feed = BinanceDataFeed(api_key, api_secret)
    strategy = build_strategy(settings.strategy)
    risk = RiskManager(settings.risk, settings.execution, settings.live)
    store = AccountStateStore(settings.logging.state_file, settings.risk.starting_capital)
    trader = PaperTrader(settings, feed, strategy, risk, store, console)

    if args.loop:
        console.log(
            f"[bold]Starting paper loop[/bold] | bot={settings.app.name} | interval={settings.app.poll_interval_sec}s "
            f"| symbol={settings.app.symbol}"
        )
        while True:
            start = time.time()
            try:
                trader.run_cycle()
            except Exception as exc:  # pragma: no cover - defensive logging
                console.log(f"[red]{settings.app.name} cycle error[/red]: {exc}")
            elapsed = time.time() - start
            sleep_for = max(0, settings.app.poll_interval_sec - elapsed)
            time.sleep(sleep_for)
    else:
        trader.run_cycle()


if __name__ == "__main__":
    main()
