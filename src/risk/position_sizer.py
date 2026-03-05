from dataclasses import dataclass


@dataclass
class PositionSizer:
    capital: float
    risk_pct: float
    max_positions: int

    def size(self, stop_loss_pct: float, price: float) -> float:
        risk_amount = self.capital * self.risk_pct
        qty = risk_amount / (price * stop_loss_pct)
        return qty
