from __future__ import annotations

import csv
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rich.console import Console

from ..config.settings import Settings
from ..data.binance_feed import BinanceDataFeed
from ..risk.manager import RiskManager
from ..strategy import StrategyAction, ConservativeTrendStrategy
from .state import AccountStateStore


class PaperTrader:
    def __init__(
        self,
        settings: Settings,
        feed: BinanceDataFeed,
        strategy: ConservativeTrendStrategy,
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

    def run_cycle(self) -> None:
        state = self.store.load()
        self.risk.refresh_daily_cap(state)
        self._validate_state(state)

        candles = self._load_candles()
        latest_price = float(candles.iloc[-1]["close"])
        timestamp = candles.iloc[-1]["open_time"].to_pydatetime()

        # Restart safety: immediately enforce SL/TP before new signals
        self._enforce_open_position_limits(state, latest_price, timestamp, context="restart-check")

        decision = self.strategy.evaluate(candles)
        log_context = {
            "timestamp": timestamp.isoformat(),
            "price": latest_price,
            **decision.features,
        }
        self._log_signal_evaluation(state, decision, log_context)

        # Manage open position after evaluating fresh signals
        self._enforce_open_position_limits(state, latest_price, timestamp, decision)

        # Consider new position if flat
        if decision.action == StrategyAction.ENTER_LONG:
            allocation = self.risk.describe_allocation(decision.strength, state)
            if not self.risk.can_open_position(state):
                if state.open_position:
                    self.console.log("[cyan]Entry blocked: position already open.")
                elif self.risk.daily_cap_breached(state):
                    self.console.log("[cyan]Entry blocked: daily loss cap reached.")
                else:
                    self.console.log("[cyan]Entry blocked: guardrail prevented trade.")
                self.console.log(
                    f"[cyan]Allocation snapshot[/cyan]: pct={allocation['allocation_pct']:.2%} "
                    f"notional={allocation['projected_notional']:.2f} balance={allocation['balance']:.2f}"
                )
            elif state.open_position:
                # Should not happen, but double-guard for safety
                self.console.log("[cyan]Entry blocked: state indicates open position after guard check.")
            else:
                plan = self.risk.plan_position(latest_price, decision.strength, state)
                if plan:
                    previous_state = "LONG" if state.open_position else "FLAT"
                    position = self.risk.open_position(self.settings.app.symbol, plan, state)
                    self._log_trade(
                        {
                            "event": "ENTER",
                            "reason": decision.reason,
                            "entry_price": position.entry_price,
                            "qty": plan.size,
                            "stop_loss": plan.stop_loss,
                            "take_profit": plan.take_profit,
                            "context": "signal-entry",
                            "equity_after_trade": state.balance,
                        }
                    )
                    self.console.log(
                        "[bold green]ENTRY[/bold green]: "
                        f"reason={decision.reason} strength={decision.strength:.2f} price={position.entry_price:.2f} "
                        f"qty={plan.size} stop={plan.stop_loss:.2f} tp={plan.take_profit:.2f}"
                    )
                    self._log_state_transition(previous_state, "LONG", "signal-entry")
                else:
                    self.console.log(
                        "[cyan]Signal present but position sizing returned None (probably insufficient balance/min notional). "
                        f"Allocation pct={allocation['allocation_pct']:.2%} notional={allocation['projected_notional']:.2f}"
                    )
        else:
            self.console.log(
                f"No entry | action={decision.action.value} | reason={decision.reason} | price={latest_price:.2f}"
            )

        self._log_blotter(state, decision, log_context)
        self.store.save(state)

    def _load_candles(self):
        min_rows = max(
            self.settings.strategy.ema_slow + 10,
            self.settings.strategy.volume_sma_period * 3,
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
            raise RuntimeError("Invalid numeric values in saved position state. Please inspect data/state file.") from exc

        numbers = [qty, entry, stop, tp]
        if any(math.isnan(n) or n <= 0 for n in numbers) or not (stop < entry < tp):
            self.console.log(
                "[red]State integrity failed (qty/price/SL/TP). Closing position at entry to preserve balance integrity."
            )
            self.risk.close_position(entry, state, "state-invalid")

    def _enforce_open_position_limits(self, state, price, timestamp, decision=None, context="loop") -> None:
        pos = state.open_position
        if not pos:
            return

        trigger_reason = None
        trigger_label = None

        if price <= pos.stop_loss:
            if context == "restart-check":
                trigger_reason = f"gap-stop (price {price:.2f} <= SL {pos.stop_loss:.2f})"
                trigger_label = "GAP_STOP"
            else:
                trigger_reason = "stop-loss"
                trigger_label = "STOP_LOSS"
        elif price >= pos.take_profit:
            if context == "restart-check":
                trigger_reason = f"gap-tp (price {price:.2f} >= TP {pos.take_profit:.2f})"
                trigger_label = "GAP_TP"
            else:
                trigger_reason = "take-profit"
                trigger_label = "TAKE_PROFIT"
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
        pnl_pct = ((price - entry_price) / entry_price) * 100 if entry_price else 0.0
        win_loss = "BREAKEVEN"
        if pnl > 0:
            win_loss = "WIN"
        elif pnl < 0:
            win_loss = "LOSS"

        self._log_trade(
            {
                "event": "EXIT",
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
        if trigger_label in {"GAP_STOP", "GAP_TP"}:
            self.console.log(
                f"[yellow]Gap exit[/yellow]: {trigger_label} price={price:.2f} "
                f"sl={snapshot.stop_loss:.2f} tp={snapshot.take_profit:.2f} | PnL={pnl:.2f}"
            )
        else:
            self.console.log(f"[yellow]Position closed[/yellow]: {trigger_reason} ({trigger_label}) | PnL={pnl:.2f}")
        self._log_state_transition("LONG", "FLAT", trigger_label or "position-close")

    def _log_trade(self, row: dict) -> None:
        self.trade_log_path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not self.trade_log_path.exists()
        row_timestamp = row.pop("timestamp_override", datetime.now(timezone.utc).isoformat())
        fields = [
            "timestamp",
            "event",
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
        features = decision.features or {}
        fields = [
            "timestamp",
            "price",
            "action",
            "reason",
            "strength",
            "trend_up",
            "rsi_in_band",
            "volume_ok",
            "filters_relaxed",
            "entry_mode",
            "entry_reason",
            "rsi",
            "ema_fast",
            "ema_slow",
            "volume",
            "volume_sma",
            "volume_threshold",
            "rsi_below_exit",
            "volume_filter_enabled",
            "balance",
            "open_position",
        ]
        row = {
            "timestamp": context.get("timestamp"),
            "price": context.get("price"),
            "action": decision.action.value,
            "reason": decision.reason,
            "strength": decision.strength,
            "trend_up": features.get("trend_up"),
            "rsi_in_band": features.get("rsi_in_band"),
            "volume_ok": features.get("volume_ok"),
            "filters_relaxed": features.get("filters_relaxed"),
            "entry_mode": features.get("entry_mode"),
            "entry_reason": features.get("entry_reason"),
            "rsi": features.get("rsi"),
            "ema_fast": features.get("ema_fast"),
            "ema_slow": features.get("ema_slow"),
            "volume": features.get("volume"),
            "volume_sma": features.get("volume_sma"),
            "volume_threshold": features.get("volume_threshold"),
            "rsi_below_exit": features.get("rsi_below_exit"),
            "volume_filter_enabled": features.get("volume_filter_enabled"),
            "balance": state.balance,
            "open_position": 1 if state.open_position else 0,
        }
        with self.signal_log_path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            if write_header:
                writer.writeheader()
            writer.writerow(row)

    def _log_state_transition(self, previous: str, new: str, context: str) -> None:
        if previous == new:
            return
        self.console.log(
            f"[blue]State change[/blue]: {previous} -> {new} | context={context}"
        )

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
            "open_position": 1 if state.open_position else 0,
            "daily_realized_pnl": state.daily_realized_pnl,
        }
        with self.blotter_path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            if write_header:
                writer.writeheader()
            writer.writerow(row)
