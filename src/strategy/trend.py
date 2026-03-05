from __future__ import annotations

import pandas as pd

from ..config.settings import StrategySettings
from ..indicators.ema import ema
from ..indicators.rsi import rsi
from .base import BaseStrategy, StrategyAction, StrategyDecision


class ConservativeTrendStrategy(BaseStrategy):
    def __init__(self, settings: StrategySettings):
        self.settings = settings

    def evaluate(self, df: pd.DataFrame, state=None) -> StrategyDecision:
        if len(df) < self.settings.ema_slow + 5:
            return StrategyDecision(
                action=StrategyAction.HOLD,
                reason="Insufficient history for indicators",
                strength=0.0,
                features={},
            )

        enriched = self._build_features(df)
        latest = enriched.iloc[-1]

        if self.settings.volume_filter_enabled:
            volume_threshold = latest["volume_sma"] * self.settings.volume_multiplier
            volume_ok = latest["volume"] > volume_threshold
        else:
            volume_threshold = 0.0
            volume_ok = True

        trend_up = latest["ema_fast"] > latest["ema_slow"]
        rsi_in_band = self.settings.rsi_entry_min <= latest["rsi"] <= self.settings.rsi_entry_max
        rsi_below_exit = latest["rsi"] < self.settings.rsi_exit
        exit_condition = latest["ema_fast"] < latest["ema_slow"] or latest["rsi"] >= self.settings.rsi_exit

        strength = self._signal_strength(latest)
        filters_relaxed = False
        entry_reason = None
        entry_mode = None
        if trend_up:
            if rsi_in_band and (not self.settings.volume_filter_enabled or volume_ok):
                entry_reason = "Trend + RSI + volume confirmation"
                entry_mode = "full-confirmation"
            elif rsi_in_band:
                entry_reason = "Trend + RSI (volume relaxed)"
                entry_mode = "rsi_only"
                filters_relaxed = True
            elif volume_ok and rsi_below_exit:
                entry_reason = "Trend + volume (RSI relaxed)"
                entry_mode = "volume_only"
                filters_relaxed = True
            else:
                entry_reason = "EMA crossover only (filters bypassed)"
                entry_mode = "ema_only"
                filters_relaxed = True

        features = {
            "close": float(latest["close"]),
            "ema_fast": float(latest["ema_fast"]),
            "ema_slow": float(latest["ema_slow"]),
            "rsi": float(latest["rsi"]),
            "volume": float(latest["volume"]),
            "volume_sma": float(latest["volume_sma"]),
            "volume_threshold": float(volume_threshold),
            "trend_up": bool(trend_up),
            "rsi_in_band": bool(rsi_in_band),
            "volume_ok": bool(volume_ok),
            "rsi_below_exit": bool(rsi_below_exit),
            "volume_filter_enabled": bool(self.settings.volume_filter_enabled),
            "filters_relaxed": bool(filters_relaxed),
            "entry_mode": entry_mode,
            "entry_reason": entry_reason,
        }

        if entry_reason:
            return StrategyDecision(
                action=StrategyAction.ENTER_LONG,
                reason=entry_reason,
                strength=strength,
                features=features,
            )

        if exit_condition:
            return StrategyDecision(
                action=StrategyAction.EXIT,
                reason="Trend weakening or RSI stretched",
                strength=1 - strength,
                features=features,
            )

        return StrategyDecision(
            action=StrategyAction.HOLD,
            reason="Conditions not aligned",
            strength=strength,
            features=features,
        )

    def _build_features(self, df: pd.DataFrame) -> pd.DataFrame:
        enriched = df.copy()
        enriched["ema_fast"] = ema(enriched["close"], self.settings.ema_fast)
        enriched["ema_slow"] = ema(enriched["close"], self.settings.ema_slow)
        enriched["rsi"] = rsi(enriched["close"], self.settings.rsi_period)
        enriched["volume_sma"] = enriched["volume"].rolling(self.settings.volume_sma_period).mean()
        enriched.dropna(inplace=True)
        return enriched

    def _signal_strength(self, latest_row: pd.Series) -> float:
        # Normalize EMA distance and RSI alignment to 0-1
        ema_gap = (latest_row["ema_fast"] - latest_row["ema_slow"]) / latest_row["ema_slow"]
        ema_score = max(0.0, min(1.0, ema_gap * 500))  # ~0.2% gap -> score 1

        rsi_mid = (self.settings.rsi_entry_min + self.settings.rsi_entry_max) / 2
        rsi_range = (self.settings.rsi_entry_max - self.settings.rsi_entry_min) / 2
        if rsi_range == 0:
            rsi_score = 0.0
        else:
            rsi_score = 1 - min(1.0, abs(latest_row["rsi"] - rsi_mid) / rsi_range)

        strength = (ema_score + max(0.0, rsi_score)) / 2
        return round(strength, 3)
