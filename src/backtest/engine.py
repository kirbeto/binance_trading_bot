from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import pandas as pd

from ..signals.trend_signal import TrendSignalGenerator, SignalResult


@dataclass
class BacktestMetrics:
    win_rate: float
    max_drawdown: float
    expectancy: float
    trades: int


class BacktestEngine:
    def __init__(self, capital: float, tp_pct: float, sl_pct: float, risk_pct: float, max_consecutive_losses: int):
        self.capital = capital
        self.tp_pct = tp_pct
        self.sl_pct = sl_pct
        self.risk_pct = risk_pct
        self.max_losses = max_consecutive_losses

    def run(self, df: pd.DataFrame, generator: TrendSignalGenerator, settings: dict) -> BacktestMetrics:
        balance = self.capital
        equity_curve: List[float] = [balance]
        wins = losses = 0
        trade_returns: List[float] = []
        position_open = False
        entry_price = 0.0
        loss_streak = 0

        for i in range(settings.get("ema_slow", 200), len(df)):
            if loss_streak >= self.max_losses:
                break

            window = df.iloc[: i + 1]
            signal: SignalResult = generator.generate(window, **settings)
            price = window.iloc[-1]["close"]

            if signal.signal == "BUY" and not position_open:
                position_open = True
                entry_price = price
                continue

            if position_open:
                risk_amount = balance * self.risk_pct
                if price >= entry_price * (1 + self.tp_pct):
                    pnl = risk_amount * (self.tp_pct / self.sl_pct)
                    balance += pnl
                    wins += 1
                    trade_returns.append(self.tp_pct)
                    position_open = False
                    loss_streak = 0
                elif price <= entry_price * (1 - self.sl_pct):
                    balance -= risk_amount
                    losses += 1
                    trade_returns.append(-self.sl_pct)
                    position_open = False
                    loss_streak += 1

            equity_curve.append(balance)

        win_rate = wins / (wins + losses) if (wins + losses) else 0.0
        max_drawdown = self._max_drawdown(equity_curve)
        expectancy = sum(trade_returns) / len(trade_returns) if trade_returns else 0.0

        return BacktestMetrics(
            win_rate=win_rate,
            max_drawdown=max_drawdown,
            expectancy=expectancy,
            trades=wins + losses,
        )

    @staticmethod
    def _max_drawdown(curve: List[float]) -> float:
        peak = curve[0]
        mdd = 0.0
        for value in curve:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak
            mdd = max(mdd, drawdown)
        return mdd
