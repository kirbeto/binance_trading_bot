"""Live trading entrypoint with hardened safety confirmations."""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

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
from src.execution.live import LiveTrader
from src.execution.state import AccountStateStore
from src.risk.manager import RiskManager
from src.strategy.trend import ConservativeTrendStrategy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Binance spot live trader (safety-first)")
    parser.add_argument("--config", default="config/bot.yaml", help="Path to YAML config")
    parser.add_argument("--loop", action="store_true", help="Continuously run with configured interval")
    parser.add_argument("--dry-run", action="store_true", help="Skip actual order placement but run live logic")
    parser.add_argument(
        "--confirm-live",
        dest="confirm_live",
        help="Confirmation phrase required to run (must be exactly 'I_UNDERSTAND_THE_RISK')",
    )
    return parser.parse_args()


def enforce_confirmation(args: argparse.Namespace) -> None:
    if args.confirm_live != LiveTrader.CONFIRM_PHRASE:
        raise SystemExit(
            "Live mode locked. Pass --confirm-live 'I_UNDERSTAND_THE_RISK' to acknowledge the risk envelope."
        )


def main() -> None:
    args = parse_args()
    console = Console()
    enforce_confirmation(args)
    settings = load_settings(args.config)

    if settings.app.mode != "live" and not args.dry_run:
        raise SystemExit("Config app.mode must be 'live' before enabling live execution.")

    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    if not args.dry_run and (not api_key or not api_secret):
        raise SystemExit("BINANCE_API_KEY/SECRET required for live trading.")

    feed = BinanceDataFeed(api_key, api_secret)
    strategy = ConservativeTrendStrategy(settings.strategy)
    risk = RiskManager(settings.risk)
    store = AccountStateStore(settings.logging.live_state_file, settings.risk.starting_capital)
    trader = LiveTrader(settings, feed, strategy, risk, store, feed.client, dry_run=args.dry_run, console=console)

    if args.loop:
        console.log(
            f"[bold]Starting LIVE loop[/bold] | interval={settings.app.poll_interval_sec}s | "
            f"symbol={settings.app.symbol} | dry_run={args.dry_run}"
        )
        while True:
            start = time.time()
            try:
                trader.run_cycle()
            except Exception as exc:  # pragma: no cover
                console.log(f"[red]Live cycle error[/red]: {exc}")
            elapsed = time.time() - start
            sleep_for = max(0, settings.app.poll_interval_sec - elapsed)
            time.sleep(sleep_for)
    else:
        trader.run_cycle()


if __name__ == "__main__":
    main()
