from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..config.settings import ExecutionSettings, LiveSettings, RiskSettings
from ..execution.state import AccountState, Position


@dataclass
class PositionPlan:
    size: float
    margin: float
    notional: float
    stop_loss: float
    take_profit: float
    side: str
    reason: str


class RiskManager:
    def __init__(self, settings: RiskSettings, execution: ExecutionSettings, live: LiveSettings):
        self.settings = settings
        self.execution = execution
        self.live = live

    def refresh_daily_cap(self, state: AccountState) -> None:
        last_reset = datetime.fromisoformat(state.daily_reset_at)
        now = datetime.now(timezone.utc)
        if now.date() != last_reset.date():
            state.daily_realized_pnl = 0.0
            state.daily_reset_at = now.isoformat()

    def daily_cap_breached(self, state: AccountState) -> bool:
        threshold = -self.settings.daily_loss_cap_pct * state.starting_balance
        return state.daily_realized_pnl <= threshold

    def can_open_position(self, state: AccountState) -> bool:
        if state.open_position is not None:
            return False
        if self.daily_cap_breached(state):
            return False
        if state.balance <= self.live.min_notional:
            return False
        return True

    def describe_allocation(self, strength: float, state: AccountState) -> dict:
        pct = self._position_pct(strength)
        margin = state.balance * pct
        notional = margin * self.execution.leverage
        return {
            "allocation_pct": pct,
            "projected_margin": margin,
            "projected_notional": notional,
            "balance": state.balance,
        }

    def plan_position(self, price: float, strength: float, state: AccountState, side: str) -> PositionPlan | None:
        pct = self._position_pct(strength)
        margin = state.balance * pct
        if margin <= 0 or margin > state.balance:
            return None

        leverage = self.execution.leverage if side == "SHORT" or self.execution.trade_side != "long" else 1.0
        notional = margin * leverage
        if notional < self.live.min_notional:
            return None

        qty = round(notional / price, 6)
        if qty <= 0:
            return None

        stop_loss = price * (1 - self.settings.stop_loss_pct) if side == "LONG" else price * (1 + self.settings.stop_loss_pct)
        tp_pct = self.settings.take_profit_pct or (self.settings.stop_loss_pct * self.settings.take_profit_rr)
        take_profit = price * (1 + tp_pct) if side == "LONG" else price * (1 - tp_pct)
        return PositionPlan(
            size=qty,
            margin=margin,
            notional=qty * price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            side=side,
            reason=f"risk_pct={pct:.2%}",
        )

    def open_position(self, symbol: str, plan: PositionPlan, state: AccountState) -> Position:
        state.balance -= plan.margin
        position = Position(
            symbol=symbol,
            entry_price=plan.notional / plan.size,
            quantity=plan.size,
            stop_loss=plan.stop_loss,
            take_profit=plan.take_profit,
            opened_at=datetime.now(timezone.utc).isoformat(),
            side=plan.side,
            leverage=self.execution.leverage if plan.side == "SHORT" else 1.0,
            margin_mode=self.execution.margin_mode,
            margin_used=plan.margin,
            notional=plan.notional,
        )
        state.open_position = position
        return position

    def close_position(self, price: float, state: AccountState, reason: str, fees: float = 0.0) -> dict:
        position = state.open_position
        if not position:
            return {"status": "noop"}

        notional_entry = position.quantity * position.entry_price
        notional_exit = position.quantity * price
        total_fees = fees + getattr(position, "fees_paid", 0.0)

        if position.side == "LONG":
            pnl = notional_exit - notional_entry - total_fees
        else:
            pnl = notional_entry - notional_exit - total_fees

        state.balance += position.margin_used + pnl
        state.realized_pnl += pnl
        state.daily_realized_pnl += pnl
        state.open_position = None
        return {
            "status": "closed",
            "pnl": pnl,
            "reason": reason,
            "proceeds": notional_exit,
            "fees": total_fees,
        }

    def _position_pct(self, strength: float) -> float:
        strength = max(0.0, min(1.0, strength))
        span = self.settings.position_pct_max - self.settings.position_pct_min
        return self.settings.position_pct_min + span * strength
