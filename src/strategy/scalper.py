from __future__ import annotations

import pandas as pd

from ..config.settings import StrategySettings
from ..indicators.ema import ema
from ..indicators.rsi import rsi
from .base import BaseStrategy, StrategyAction, StrategyDecision


class ScalperStrategy(BaseStrategy):
    def __init__(self, settings: StrategySettings):
        self.settings = settings

    def evaluate(self, df: pd.DataFrame, state=None) -> StrategyDecision:
        enriched = self._prepare(df)
        if enriched is None:
            return StrategyDecision(
                action=StrategyAction.HOLD,
                reason="Insufficient history",
                strength=0.0,
                features={},
            )

        latest = enriched.iloc[-1]
        prev = enriched.iloc[-2]
        features = self._build_features(enriched)
        in_position = getattr(state, "open_position", None)
        current_side = getattr(in_position, "side", None)

        cross_up = prev["ema_fast"] <= prev["ema_slow"] and latest["ema_fast"] > latest["ema_slow"]
        cross_down = prev["ema_fast"] >= prev["ema_slow"] and latest["ema_fast"] < latest["ema_slow"]
        rsi_band_ok = self.settings.rsi_entry_min <= latest["rsi"] <= self.settings.rsi_entry_max

        long_exit_rsi = self.settings.rsi_exit_upper or (self.settings.rsi_entry_max + 5)
        short_exit_rsi = self.settings.rsi_exit_lower or (self.settings.rsi_entry_min - 5)

        if not in_position and rsi_band_ok:
            if cross_up:
                return StrategyDecision(
                    action=StrategyAction.ENTER_LONG,
                    reason="Scalper long crossover",
                    strength=self._strength(latest),
                    features=features,
                )
            if cross_down:
                return StrategyDecision(
                    action=StrategyAction.ENTER_SHORT,
                    reason="Scalper short crossover",
                    strength=self._strength(latest),
                    features=features,
                )

        if current_side == "LONG" and (cross_down or latest["rsi"] >= long_exit_rsi):
            return StrategyDecision(
                action=StrategyAction.EXIT,
                reason="Scalper long exit",
                strength=1.0,
                features=features,
            )

        if current_side == "SHORT" and (cross_up or latest["rsi"] <= short_exit_rsi):
            return StrategyDecision(
                action=StrategyAction.EXIT,
                reason="Scalper short exit",
                strength=1.0,
                features=features,
            )

        hold_reason = "Waiting for crossover"
        if in_position:
            hold_reason = f"Managing {current_side.lower()}"
        return StrategyDecision(
            action=StrategyAction.HOLD,
            reason=hold_reason,
            strength=self._strength(latest),
            features=features,
        )

    def _prepare(self, df: pd.DataFrame) -> pd.DataFrame | None:
        if len(df) < max(self.settings.ema_slow + 5, 50):
            return None
        enriched = df.copy()
        enriched["ema_fast"] = ema(enriched["close"], self.settings.ema_fast)
        enriched["ema_slow"] = ema(enriched["close"], self.settings.ema_slow)
        enriched["rsi"] = rsi(enriched["close"], self.settings.rsi_period)
        enriched.dropna(inplace=True)
        if len(enriched) < 2:
            return None
        return enriched

    def _build_features(self, enriched: pd.DataFrame) -> dict:
        latest = enriched.iloc[-1]
        return {
            "close": float(latest["close"]),
            "ema_fast": float(latest["ema_fast"]),
            "ema_slow": float(latest["ema_slow"]),
            "rsi": float(latest["rsi"]),
        }

    def _strength(self, latest: pd.Series) -> float:
        ema_gap = abs(latest["ema_fast"] - latest["ema_slow"]) / max(latest["ema_slow"], 1e-9)
        ema_score = max(0.0, min(1.0, ema_gap * 1200))
        rsi_mid = (self.settings.rsi_entry_min + self.settings.rsi_entry_max) / 2
        rsi_range = max(2, self.settings.rsi_entry_max - self.settings.rsi_entry_min)
        rsi_score = 1 - min(1.0, abs(latest["rsi"] - rsi_mid) / rsi_range)
        return round(max(0.0, (ema_score + rsi_score) / 2), 3)
