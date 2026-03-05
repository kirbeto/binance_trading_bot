from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..config.settings import RiskSettings
from ..execution.state import AccountState, Position


@dataclass
class PositionPlan:
    size: float
    cost: float
    stop_loss: float
    take_profit: float
    reason: str


class RiskManager:
    def __init__(self, settings: RiskSettings):
        self.settings = settings

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
        if state.balance <= 5:  # Binance minimum notional guard
            return False
        return True

    def describe_allocation(self, strength: float, state: AccountState) -> dict:
        pct = self._position_pct(strength)
        return {
            "allocation_pct": pct,
            "projected_notional": state.balance * pct,
            "balance": state.balance,
        }

    def plan_position(self, price: float, strength: float, state: AccountState) -> PositionPlan | None:
        pct = self._position_pct(strength)
        notional = state.balance * pct
        if notional <= 5 or notional > state.balance:
            return None

        qty = round(notional / price, 6)
        if qty <= 0:
            return None

        stop_loss = price * (1 - self.settings.stop_loss_pct)
        take_profit = price * (1 + self.settings.stop_loss_pct * self.settings.take_profit_rr)
        return PositionPlan(
            size=qty,
            cost=qty * price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            reason=f"risk_pct={pct:.2%}",
        )

    def open_position(self, symbol: str, plan: PositionPlan, state: AccountState) -> Position:
        state.balance -= plan.cost
        position = Position(
            symbol=symbol,
            entry_price=plan.cost / plan.size,
            quantity=plan.size,
            stop_loss=plan.stop_loss,
            take_profit=plan.take_profit,
            opened_at=datetime.now(timezone.utc).isoformat(),
        )
        state.open_position = position
        return position

    def close_position(self, price: float, state: AccountState, reason: str, fees: float = 0.0) -> dict:
        position = state.open_position
        if not position:
            return {"status": "noop"}

        proceeds = position.quantity * price
        entry_cost = position.quantity * position.entry_price
        total_fees = fees + getattr(position, "fees_paid", 0.0)
        pnl = proceeds - entry_cost - total_fees
        state.balance += proceeds
        state.realized_pnl += pnl
        state.daily_realized_pnl += pnl
        state.open_position = None
        return {
            "status": "closed",
            "pnl": pnl,
            "reason": reason,
            "proceeds": proceeds,
            "fees": total_fees,
        }

    def _position_pct(self, strength: float) -> float:
        strength = max(0.0, min(1.0, strength))
        span = self.settings.position_pct_max - self.settings.position_pct_min
        return self.settings.position_pct_min + span * strength
