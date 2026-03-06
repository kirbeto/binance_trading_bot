"""Run multiple bot configs in parallel threads (paper or live)."""

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
from src.execution.live import LiveTrader
from src.execution.paper import PaperTrader
from src.execution.state import AccountStateStore
from src.risk.manager import RiskManager
from src.strategy import ConservativeTrendStrategy, build_strategy


class BotWorker(threading.Thread):
    def __init__(
        self,
        config_path: str,
        api_key: str | None,
        api_secret: str | None,
        console: Console,
        confirm_phrase: str | None,
        dry_run: bool,
    ):
        super().__init__(daemon=True)
        self.config_path = config_path
        self.console = console
        self.settings = load_settings(config_path)
        if self.settings.app.mode == "live" and not dry_run and (not api_key or not api_secret):
            raise SystemExit(
                f"Live bot '{self.settings.app.name}' requires BINANCE_API_KEY and BINANCE_API_SECRET."
            )
        self.api_key = api_key
        self.api_secret = api_secret
        self.interval = self.settings.app.poll_interval_sec
        self.dry_run = dry_run

        self.feed = BinanceDataFeed(api_key, api_secret)
        self.strategy = self._build_strategy()
        self.risk = RiskManager(self.settings.risk, self.settings.execution, self.settings.live)

        if self.settings.app.mode == "live":
            self._enforce_confirmation(confirm_phrase)
            state_path = self.settings.logging.live_state_file
            store = AccountStateStore(state_path, self.settings.risk.starting_capital)
            self.trader = LiveTrader(
                self.settings,
                self.feed,
                self.strategy,
                self.risk,
                store,
                self.feed.client,
                dry_run=dry_run,
                console=console,
            )
        else:
            state_path = self.settings.logging.state_file
            store = AccountStateStore(state_path, self.settings.risk.starting_capital)
            self.trader = PaperTrader(self.settings, self.feed, self.strategy, self.risk, store, console)

    def _build_strategy(self):
        if self.settings.app.mode == "live" and self.settings.strategy.type == "trend_long":
            return ConservativeTrendStrategy(self.settings.strategy)
        return build_strategy(self.settings.strategy)

    def _enforce_confirmation(self, phrase: str | None) -> None:
        if self.dry_run:
            return
        if phrase != LiveTrader.CONFIRM_PHRASE:
            raise SystemExit(
                f"Live bot '{self.settings.app.name}' requires confirmation phrase {LiveTrader.CONFIRM_PHRASE}."
            )

    def run(self) -> None:
        mode = "LIVE" if self.settings.app.mode == "live" and not self.dry_run else "PAPER"
        self.console.log(
            f"[bold]Starting {mode} bot[/bold] {self.settings.app.name} from {self.config_path} | dry_run={self.dry_run}"
        )
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
    parser.add_argument(
        "--confirm-live",
        dest="confirm_live",
        help="Confirmation phrase required before enabling live execution",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip actual order placement for live bots while keeping live logic",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    console = Console()
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")

    workers = [
        BotWorker(cfg, api_key, api_secret, console, args.confirm_live, args.dry_run)
        for cfg in args.configs
    ]
    for worker in workers:
        worker.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        console.log("Stopping bots...")


if __name__ == "__main__":
    main()
