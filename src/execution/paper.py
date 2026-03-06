from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rich.console import Console

from ..config.settings import Settings
from ..data.binance_feed import BinanceDataFeed
from ..risk.manager import RiskManager
from ..strategy import BaseStrategy, StrategyAction
from .state import AccountStateStore


class PaperTrader:
    def __init__(
        self,
        settings: Settings,
        feed: BinanceDataFeed,
        strategy: BaseStrategy,
        risk_manager: RiskManager,
        store: AccountStateStore,
        console: Optional[Console] = None,
    ) -> None:
        self.settings = settings
        self.feed = feed
        self.strategy = strategy
        self.risk = risk_manager
        self.store = store
        self.console = console or Console()
        self.trade_log_path = Path(self.settings.logging.trade_log)
        self.blotter_path = Path(self.settings.logging.blotter_log)
        self.signal_log_path = Path(self.settings.logging.signal_log)
        self.bot_label = f"[{self.settings.app.name}]"

    def run_cycle(self) -> None:
        state = self.store.load()
        self.risk.refresh_daily_cap(state)
        self._validate_state(state)

        candles = self._load_candles()
        latest_price = float(candles.iloc[-1]["close"])
        timestamp = candles.iloc[-1]["open_time"].to_pydatetime()

        # Safety check before processing new signals
        self._enforce_open_position_limits(state, latest_price, timestamp, context="restart-check")

        decision = self.strategy.evaluate(candles, state)
        log_context = {
            "timestamp": timestamp.isoformat(),
            "price": latest_price,
            **(decision.features or {}),
        }
        self._log_signal_evaluation(state, decision, log_context)

        # Manage open position after evaluating fresh signals
        self._enforce_open_position_limits(state, latest_price, timestamp, decision)

        if decision.action in {StrategyAction.ENTER_LONG, StrategyAction.ENTER_SHORT}:
            self._handle_entry(decision, state, latest_price)
        elif decision.action == StrategyAction.EXIT:
            self._log("Exit signal observed (handled in enforcement block)")
        else:
            self._log(
                f"No entry | action={decision.action.value} | reason={decision.reason} | price={latest_price:.2f}"
            )

        self._log_blotter(state, decision, log_context)
        self.store.save(state)

    def _handle_entry(self, decision, state, latest_price):
        side = "LONG" if decision.action == StrategyAction.ENTER_LONG else "SHORT"
        if not self._side_allowed(side):
            self._log(f"{side} entry blocked: side restricted by config")
            return

        allocation = self.risk.describe_allocation(decision.strength, state)
        if not self.risk.can_open_position(state):
            reason = "open position" if state.open_position else "risk guard"
            self._log(f"Entry blocked ({reason}). allocation={allocation}")
            return

        plan = self.risk.plan_position(latest_price, decision.strength, state, side)
        if not plan:
            self._log(
                "Signal present but position sizing returned None "
                f"(balance={state.balance:.2f}, allocation={allocation['allocation_pct']:.2%})"
            )
            return

        position = self.risk.open_position(self.settings.app.symbol, plan, state)
        self._log(
            f"ENTRY {side}: reason={decision.reason} strength={decision.strength:.2f} "
            f"price={position.entry_price:.2f} qty={plan.size} stop={plan.stop_loss:.2f} tp={plan.take_profit:.2f}"
        )
        self._log_trade(
            {
                "event": "ENTER",
                "side": side,
                "reason": decision.reason,
                "entry_price": position.entry_price,
                "qty": plan.size,
                "stop_loss": plan.stop_loss,
                "take_profit": plan.take_profit,
                "context": "signal-entry",
                "equity_after_trade": state.balance,
            }
        )

    def _side_allowed(self, side: str) -> bool:
        config_side = self.settings.execution.trade_side
        if config_side == "both":
            return True
        return (side == "LONG" and config_side == "long") or (side == "SHORT" and config_side == "short")

    def _load_candles(self):
        min_rows = max(
            self.settings.strategy.ema_slow + 10,
            self.settings.strategy.volume_sma_period * 3,
            self.settings.strategy.history_bars,
        )
        return self.feed.fetch_candles(
            symbol=self.settings.app.symbol,
            interval=self.settings.app.interval,
            limit=min_rows,
        )

    def _validate_state(self, state):
        pos = state.open_position
        if not pos:
            return
        try:
            qty = float(pos.quantity)
            entry = float(pos.entry_price)
            stop = float(pos.stop_loss)
            tp = float(pos.take_profit)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Invalid numeric values in saved position state. Please inspect state file.") from exc

        numbers = [qty, entry, stop, tp]
        if any(math.isnan(n) or n <= 0 for n in numbers):
            self._log("State integrity failed. Closing position at entry to preserve balance integrity.")
            self.risk.close_position(entry, state, "state-invalid")

    def _enforce_open_position_limits(self, state, price, timestamp, decision=None, context="loop") -> None:
        pos = state.open_position
        if not pos:
            return

        trigger_reason = None
        trigger_label = None

        if pos.side == "LONG":
            stop_hit = price <= pos.stop_loss
            tp_hit = price >= pos.take_profit
        else:
            stop_hit = price >= pos.stop_loss
            tp_hit = price <= pos.take_profit

        if stop_hit:
            trigger_reason = "stop-loss" if context == "loop" else "gap-stop"
            trigger_label = "STOP_LOSS" if context == "loop" else "GAP_STOP"
        elif tp_hit:
            trigger_reason = "take-profit" if context == "loop" else "gap-tp"
            trigger_label = "TAKE_PROFIT" if context == "loop" else "GAP_TP"
        elif decision and decision.action == StrategyAction.EXIT:
            trigger_reason = decision.reason
            trigger_label = "SIGNAL_EXIT"

        if not trigger_reason:
            return

        snapshot = state.open_position
        result = self.risk.close_position(price, state, trigger_reason)
        pnl = float(result.get("pnl", 0.0))
        entry_price = snapshot.entry_price
        entry_time = datetime.fromisoformat(snapshot.opened_at)
        duration_sec = max(0, (timestamp - entry_time).total_seconds())
        if snapshot.side == "LONG":
            pnl_pct = ((price - entry_price) / entry_price) * 100 if entry_price else 0.0
        else:
            pnl_pct = ((entry_price - price) / entry_price) * 100 if entry_price else 0.0
        win_loss = "BREAKEVEN"
        if pnl > 0:
            win_loss = "WIN"
        elif pnl < 0:
            win_loss = "LOSS"

        self._log_trade(
            {
                "event": "EXIT",
                "side": snapshot.side,
                "reason": trigger_reason,
                "entry_price": entry_price,
                "exit_price": price,
                "qty": snapshot.quantity,
                "stop_loss": snapshot.stop_loss,
                "take_profit": snapshot.take_profit,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "trade_duration_sec": duration_sec,
                "win_or_loss": win_loss,
                "equity_after_trade": state.balance,
                "context": trigger_label,
                "timestamp_override": timestamp.isoformat(),
            }
        )
        self._log(
            f"Position closed ({snapshot.side}) reason={trigger_reason} pnl={pnl:.2f} balance={state.balance:.2f}"
        )

    def _log_trade(self, row: dict) -> None:
        self.trade_log_path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not self.trade_log_path.exists()
        row_timestamp = row.pop("timestamp_override", datetime.now(timezone.utc).isoformat())
        fields = [
            "timestamp",
            "event",
            "side",
            "context",
            "reason",
            "entry_price",
            "exit_price",
            "qty",
            "stop_loss",
            "take_profit",
            "pnl",
            "pnl_pct",
            "trade_duration_sec",
            "win_or_loss",
            "equity_after_trade",
        ]
        record = {field: row.get(field) for field in fields if field != "timestamp"}
        record["timestamp"] = row_timestamp
        with self.trade_log_path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            if write_header:
                writer.writeheader()
            writer.writerow(record)

    def _log_signal_evaluation(self, state, decision, context) -> None:
        self.signal_log_path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not self.signal_log_path.exists()
        fields = [
            "timestamp",
            "price",
            "action",
            "reason",
            "strength",
            "balance",
            "open_position",
            "features",
        ]
        row = {
            "timestamp": context.get("timestamp"),
            "price": context.get("price"),
            "action": decision.action.value,
            "reason": decision.reason,
            "strength": decision.strength,
            "balance": state.balance,
            "open_position": getattr(state.open_position, "side", "FLAT"),
            "features": json.dumps(decision.features or {}),
        }
        with self.signal_log_path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            if write_header:
                writer.writeheader()
            writer.writerow(row)

    def _log_state_transition(self, previous: str, new: str, context: str) -> None:
        if previous == new:
            return
        self._log(f"State change {previous} -> {new} | context={context}")

    def _log_blotter(self, state, decision, context) -> None:
        self.blotter_path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not self.blotter_path.exists()
        fields = [
            "timestamp",
            "price",
            "action",
            "reason",
            "strength",
            "balance",
            "open_position",
            "daily_realized_pnl",
        ]
        row = {
            "timestamp": context["timestamp"],
            "price": context.get("price"),
            "action": decision.action.value,
            "reason": decision.reason,
            "strength": decision.strength,
            "balance": state.balance,
            "open_position": getattr(state.open_position, "side", "FLAT"),
            "daily_realized_pnl": state.daily_realized_pnl,
        }
        with self.blotter_path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            if write_header:
                writer.writeheader()
            writer.writerow(row)

    def _log(self, message: str) -> None:
        self.console.log(f"{self.bot_label} {message}")
