from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from binance.client import Client
from rich.console import Console

from ..config.settings import Settings
from ..data.binance_feed import BinanceDataFeed
from ..risk.manager import PositionPlan, RiskManager
from ..strategy import BaseStrategy, StrategyAction
from .state import AccountStateStore


class LiveTrader:
    """Live execution layer that mirrors PaperTrader but talks to Binance endpoints."""

    CONFIRM_PHRASE = "I_UNDERSTAND_THE_RISK"

    def __init__(
        self,
        settings: Settings,
        feed: BinanceDataFeed,
        strategy: BaseStrategy,
        risk_manager: RiskManager,
        store: AccountStateStore,
        client: Client,
        dry_run: bool = False,
        console: Optional[Console] = None,
    ) -> None:
        self.settings = settings
        self.feed = feed
        self.strategy = strategy
        self.risk = risk_manager
        self.store = store
        self.client = client
        self.dry_run = dry_run
        self.console = console or Console()
        self.market = settings.execution.market

        self.trade_log_path = Path(self.settings.logging.live_trade_log)
        self.execution_log_path = Path(self.settings.logging.live_execution_log)
        self.signal_log_path = Path(self.settings.logging.live_signal_log)
        self.trade_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.execution_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.signal_log_path.parent.mkdir(parents=True, exist_ok=True)

        (
            self.symbol_info,
            self.base_asset,
            self.quote_asset,
            self.step_size,
            self.min_qty,
            self.exchange_min_notional,
        ) = self._load_symbol_metadata()

        self.live_cfg = settings.live
        self.min_notional = max(self.live_cfg.min_notional, self.exchange_min_notional)
        self.fee_rate = self.live_cfg.fee_bps / 10_000

    def run_cycle(self) -> None:
        state = self.store.load()
        self.risk.refresh_daily_cap(state)
        self._sync_balance_with_exchange(state)

        if state.balance < self.live_cfg.min_balance:
            self.console.log(
                f"[red]Live mode blocked[/red]: balance {state.balance:.2f} < min {self.live_cfg.min_balance:.2f}"
            )
            self.store.save(state)
            return

        candles = self._load_candles()
        latest_price = float(candles.iloc[-1]["close"])
        timestamp = candles.iloc[-1]["open_time"].to_pydatetime()

        self._enforce_open_position_limits(state, latest_price, timestamp, context="restart-check")

        decision = self.strategy.evaluate(candles, state)
        log_context = {
            "timestamp": timestamp.isoformat(),
            "price": latest_price,
            **(decision.features or {}),
        }
        self._log_signal_evaluation(state, decision, log_context)

        self._enforce_open_position_limits(state, latest_price, timestamp, decision=decision, context="loop")

        if decision.action in {StrategyAction.ENTER_LONG, StrategyAction.ENTER_SHORT}:
            side = "LONG" if decision.action == StrategyAction.ENTER_LONG else "SHORT"
            self._attempt_entry(side, decision, state, latest_price, timestamp)
        elif decision.action == StrategyAction.EXIT:
            self.console.log(
                "Exit signal observed; waiting for enforcement block to flatten if conditions are met."
            )
        else:
            self.console.log(
                f"Live mode no-entry | action={decision.action.value} | reason={decision.reason} | price={latest_price:.2f}"
            )

        self.store.save(state)

    # ------------------------------------------------------------------
    # Entry helpers
    # ------------------------------------------------------------------
    def _attempt_entry(self, side: str, decision, state, latest_price: float, timestamp) -> None:
        if side == "SHORT" and self.market == "spot":
            self.console.log(
                "[cyan]Short entry skipped[/cyan]: spot market is long-only. Configure futures to enable shorts."
            )
            return

        allocation = self.risk.describe_allocation(decision.strength, state)
        if not self.risk.can_open_position(state):
            self.console.log(
                f"[cyan]Live entry skipped[/cyan]: guardrail prevented trade. allocation={allocation}"
            )
            return

        plan = self.risk.plan_position(latest_price, decision.strength, state, side)
        if not plan:
            self.console.log(
                "[cyan]Live entry skipped[/cyan]: insufficient capital for planned trade."
            )
            return

        qty = self._quantize_quantity(plan.size)
        notional = qty * latest_price
        if qty < self.min_qty or notional < self.min_notional:
            self.console.log(
                "[cyan]Live entry skipped[/cyan]: below min qty/notional | "
                f"qty={qty} notional={notional:.2f} min_notional={self.min_notional:.2f}"
            )
            return

        order_side = "BUY" if side == "LONG" else "SELL"
        self._enter_position(state, plan, qty, latest_price, decision, timestamp, order_side, side)

    def _enter_position(
        self,
        state,
        plan: PositionPlan,
        qty: float,
        signal_price: float,
        decision,
        timestamp,
        order_side: str,
        position_side: str,
    ) -> None:
        order = self._place_market_order(order_side, qty, signal_price)
        fill_price = self._extract_fill_price(order, signal_price)
        executed_qty = float(order.get("executedQty") or qty) if order else qty
        notional = fill_price * executed_qty
        entry_fee = notional * self.fee_rate

        realized_plan = PositionPlan(
            size=executed_qty,
            margin=plan.margin,
            notional=notional,
            stop_loss=plan.stop_loss,
            take_profit=plan.take_profit,
            side=position_side,
            reason=plan.reason,
        )
        position = self.risk.open_position(self.settings.app.symbol, realized_plan, state)
        position.fees_paid = entry_fee

        slippage = fill_price - signal_price
        self._log_trade(
            {
                "event": "ENTER",
                "side": position_side,
                "reason": decision.reason,
                "signal_price": signal_price,
                "fill_price": fill_price,
                "slippage": slippage,
                "qty": executed_qty,
                "stop_loss": plan.stop_loss,
                "take_profit": plan.take_profit,
                "fees": entry_fee,
                "context": "signal-entry",
            }
        )
        self.console.log(
            f"[bold green]LIVE ENTRY[/bold green]: side={position_side} "
            f"price={fill_price:.2f} signal_price={signal_price:.2f} slippage={slippage:.2f} qty={executed_qty}"
        )

    # ------------------------------------------------------------------
    # Risk + exit helpers
    # ------------------------------------------------------------------
    def _enforce_open_position_limits(self, state, price, timestamp, decision=None, context="loop") -> None:
        pos = state.open_position
        if not pos:
            return

        if pos.side == "LONG":
            stop_hit = price <= pos.stop_loss
            tp_hit = price >= pos.take_profit
        else:
            stop_hit = price >= pos.stop_loss
            tp_hit = price <= pos.take_profit

        trigger_reason = None
        trigger_label = None

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

        self._exit_position(state, price, trigger_reason, trigger_label, timestamp)

    def _exit_position(self, state, price_hint, reason: str, label: str, timestamp) -> None:
        pos = state.open_position
        if not pos:
            return

        order_side = "SELL" if pos.side == "LONG" else "BUY"
        order = self._place_market_order(order_side, pos.quantity, price_hint)
        fill_price = self._extract_fill_price(order, price_hint)
        executed_qty = float(order.get("executedQty", pos.quantity)) if order else pos.quantity
        notional = fill_price * executed_qty
        exit_fee = notional * self.fee_rate
        result = self.risk.close_position(fill_price, state, reason, fees=exit_fee)

        pnl = float(result.get("pnl", 0.0))
        entry_price = pos.entry_price
        if pos.side == "LONG":
            pnl_pct = ((fill_price - entry_price) / entry_price) * 100 if entry_price else 0.0
        else:
            pnl_pct = ((entry_price - fill_price) / entry_price) * 100 if entry_price else 0.0
        slippage = fill_price - price_hint

        self._log_trade(
            {
                "event": "EXIT",
                "side": pos.side,
                "reason": reason,
                "signal_price": price_hint,
                "fill_price": fill_price,
                "slippage": slippage,
                "qty": executed_qty,
                "fees": exit_fee + getattr(pos, "fees_paid", 0.0),
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "context": label,
            }
        )
        self.console.log(
            f"[yellow]LIVE EXIT[/yellow]: side={pos.side} {label} fill={fill_price:.2f} "
            f"signal_price={price_hint:.2f} slippage={slippage:.2f} pnl={pnl:.2f}"
        )

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------
    def _log_trade(self, row: dict) -> None:
        write_header = not self.trade_log_path.exists()
        timestamp = datetime.now(timezone.utc).isoformat()
        fields = [
            "timestamp",
            "event",
            "side",
            "context",
            "reason",
            "signal_price",
            "fill_price",
            "slippage",
            "qty",
            "stop_loss",
            "take_profit",
            "fees",
            "pnl",
            "pnl_pct",
        ]
        record = {field: row.get(field) for field in fields}
        record["timestamp"] = timestamp
        with self.trade_log_path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            if write_header:
                writer.writeheader()
            writer.writerow(record)

    def _log_signal_evaluation(self, state, decision, context) -> None:
        write_header = not self.signal_log_path.exists()
        fields = [
            "timestamp",
            "price",
            "action",
            "reason",
            "strength",
            "balance",
            "open_position",
            "trend_up",
            "rsi_in_band",
            "volume_ok",
            "filters_relaxed",
        ]
        row = {
            "timestamp": context.get("timestamp"),
            "price": context.get("price"),
            "action": decision.action.value,
            "reason": decision.reason,
            "strength": decision.strength,
            "balance": state.balance,
            "open_position": getattr(getattr(state, "open_position", None), "side", "FLAT"),
            "trend_up": context.get("trend_up"),
            "rsi_in_band": context.get("rsi_in_band"),
            "volume_ok": context.get("volume_ok"),
            "filters_relaxed": context.get("filters_relaxed"),
        }
        with self.signal_log_path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            if write_header:
                writer.writeheader()
            writer.writerow(row)

    def _log_order_response(self, payload: Dict[str, Any]) -> None:
        with self.execution_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, default=str))
            fh.write("\n")

    # ------------------------------------------------------------------
    # Exchange helpers
    # ------------------------------------------------------------------
    def _load_symbol_metadata(self):
        symbol = self.settings.app.symbol
        if self.market == "spot":
            info = self.client.get_symbol_info(symbol)
        else:
            exchange_info = self.client.futures_exchange_info()
            info = None
            for entry in exchange_info.get("symbols", []):
                if entry.get("symbol") == symbol:
                    info = entry
                    break
        if not info:
            raise RuntimeError(f"Symbol {symbol} metadata unavailable for {self.market} market")

        base_asset = info.get("baseAsset") or symbol[:-4]
        quote_asset = info.get("quoteAsset") or "USDT"
        filters = {flt["filterType"]: flt for flt in info.get("filters", [])}
        lot_filter = filters.get("LOT_SIZE")
        if not lot_filter:
            raise RuntimeError("LOT_SIZE filter missing; cannot quantize orders")
        step_size = float(lot_filter.get("stepSize", "0.000001"))
        min_qty = float(lot_filter.get("minQty", "0.000001"))
        notional_filter = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL")
        exchange_min_notional = float((notional_filter or {}).get("minNotional", "0"))
        return info, base_asset, quote_asset, step_size, min_qty, exchange_min_notional

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

    def _sync_balance_with_exchange(self, state) -> None:
        if self.dry_run:
            if state.starting_balance <= 0:
                state.starting_balance = state.balance
            return
        balance = self._fetch_quote_balance()
        state.balance = balance
        if state.starting_balance <= 0:
            state.starting_balance = balance

    def _fetch_quote_balance(self) -> float:
        if self.market == "spot":
            account = self.client.get_asset_balance(asset=self.quote_asset)
            if not account:
                raise RuntimeError(f"Unable to read balance for {self.quote_asset}")
            return float(account.get("free", 0.0))
        balances = self.client.futures_account_balance()
        for entry in balances:
            if entry.get("asset") == (self.quote_asset or "USDT"):
                return float(entry.get("balance", 0.0))
        raise RuntimeError(f"Unable to read futures balance for {self.quote_asset or 'USDT'}")

    def _place_market_order(self, order_side: str, quantity: float, price_hint: float) -> Dict[str, Any]:
        payload = {
            "symbol": self.settings.app.symbol,
            "side": order_side,
            "type": Client.ORDER_TYPE_MARKET,
            "quantity": quantity,
        }
        if self.dry_run:
            mock = {
                "dry_run": True,
                "symbol": payload["symbol"],
                "side": order_side,
                "executedQty": f"{quantity:.8f}",
                "cummulativeQuoteQty": f"{quantity * price_hint:.8f}",
                "transactTime": int(datetime.now(timezone.utc).timestamp() * 1000),
                "fills": [],
            }
            self._log_order_response(mock)
            return mock

        if self.market == "spot":
            order = self.client.create_order(**payload)
        else:
            order = self.client.futures_create_order(**payload)
        self._log_order_response(order)
        return order

    def _extract_fill_price(self, order: Dict[str, Any], default: float) -> float:
        if not order:
            return default
        if "avgPrice" in order and float(order.get("avgPrice") or 0) > 0:
            return float(order["avgPrice"])
        executed = float(order.get("executedQty") or 0)
        if executed <= 0:
            return default
        quote_qty = float(order.get("cummulativeQuoteQty") or 0)
        if quote_qty > 0:
            return quote_qty / executed
        return default

    def _quantize_quantity(self, qty: float) -> float:
        if qty <= 0:
            return 0.0
        if self.step_size <= 0:
            return qty
        precision = int(round(-math.log(self.step_size, 10))) if self.step_size < 1 else 0
        quantized = math.floor(qty / self.step_size) * self.step_size
        return round(quantized, precision)
