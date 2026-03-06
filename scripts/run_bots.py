"""Run multiple bot configs in parallel threads."""

from __future__ import annotations

import argparse
import os
import threading
import time
from pathlib import Path

from rich.console import Console

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_settings
from src.data.binance_feed import BinanceDataFeed
from src.execution.paper import PaperTrader
from src.execution.state import AccountStateStore
from src.risk.manager import RiskManager
from src.strategy import build_strategy


class BotWorker(threading.Thread):
    def __init__(self, config_path: str, api_key: str | None, api_secret: str | None, console: Console):
        super().__init__(daemon=True)
        self.config_path = config_path
        self.console = console
        self.settings = load_settings(config_path)
        feed = BinanceDataFeed(api_key, api_secret)
        strategy = build_strategy(self.settings.strategy)
        risk = RiskManager(self.settings.risk, self.settings.execution, self.settings.live)
        store = AccountStateStore(self.settings.logging.state_file, self.settings.risk.starting_capital)
        self.trader = PaperTrader(self.settings, feed, strategy, risk, store, console)
        self.interval = self.settings.app.poll_interval_sec

    def run(self) -> None:
        self.console.log(f"[bold]Starting bot[/bold] {self.settings.app.name} from {self.config_path}")
        while True:
            start = time.time()
            try:
                self.trader.run_cycle()
            except Exception as exc:  # pragma: no cover - defensive logging
                self.console.log(f"[red]{self.settings.app.name} error[/red]: {exc}")
            elapsed = time.time() - start
            sleep_for = max(0, self.interval - elapsed)
            time.sleep(sleep_for)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run multiple bot configs in parallel")
    parser.add_argument("--configs", nargs="+", required=True, help="Config file paths")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    console = Console()
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")

    workers = [BotWorker(cfg, api_key, api_secret, console) for cfg in args.configs]
    for worker in workers:
        worker.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        console.log("Stopping bots...")


if __name__ == "__main__":
    main()
