from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class Position:
    symbol: str
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    opened_at: str
    fees_paid: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Position":
        return cls(
            symbol=data["symbol"],
            entry_price=data["entry_price"],
            quantity=data["quantity"],
            stop_loss=data["stop_loss"],
            take_profit=data["take_profit"],
            opened_at=data.get("opened_at") or datetime.now(timezone.utc).isoformat(),
            fees_paid=data.get("fees_paid", 0.0),
        )


@dataclass
class AccountState:
    balance: float
    starting_balance: float
    open_position: Optional[Position]
    realized_pnl: float
    daily_realized_pnl: float
    daily_reset_at: str

    def to_dict(self) -> dict:
        data = asdict(self)
        if self.open_position:
            data["open_position"] = self.open_position.to_dict()
        return data

    @classmethod
    def default(cls, starting_balance: float) -> "AccountState":
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            balance=starting_balance,
            starting_balance=starting_balance,
            open_position=None,
            realized_pnl=0.0,
            daily_realized_pnl=0.0,
            daily_reset_at=now,
        )

    @classmethod
    def from_dict(cls, data: dict, fallback: float) -> "AccountState":
        position = data.get("open_position")
        return cls(
            balance=data.get("balance", fallback),
            starting_balance=data.get("starting_balance", fallback),
            open_position=Position.from_dict(position) if position else None,
            realized_pnl=data.get("realized_pnl", 0.0),
            daily_realized_pnl=data.get("daily_realized_pnl", 0.0),
            daily_reset_at=data.get("daily_reset_at") or datetime.now(timezone.utc).isoformat(),
        )


class AccountStateStore:
    def __init__(self, path: str, starting_balance: float):
        self.path = Path(path)
        self.starting_balance = starting_balance
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AccountState:
        if not self.path.exists():
            return AccountState.default(self.starting_balance)
        with self.path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return AccountState.from_dict(data, self.starting_balance)

    def save(self, state: AccountState) -> None:
        with self.path.open("w", encoding="utf-8") as fh:
            json.dump(state.to_dict(), fh, indent=2)
