from __future__ import annotations

import pandas as pd

from ..config.settings import StrategySettings
from ..indicators.ema import ema
from ..indicators.rsi import rsi
from .base import BaseStrategy, StrategyAction, StrategyDecision


class TrendLongStrategy(BaseStrategy):
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
        features = self._build_features(enriched)
        in_position = bool(getattr(state, "open_position", None))
        trend_up = latest["ema_fast"] > latest["ema_slow"]
        rsi_ok = latest["rsi"] >= self.settings.rsi_entry_min
        exit_rsi = latest["rsi"] <= self.settings.rsi_exit
        exit_trend = latest["ema_fast"] < latest["ema_slow"]

        if trend_up and rsi_ok and not in_position and features["volume_ok"]:
            strength = self._strength(latest, long_bias=True)
            return StrategyDecision(
                action=StrategyAction.ENTER_LONG,
                reason="Trend + RSI confirmation",
                strength=strength,
                features=features,
            )

        if in_position and (exit_rsi or exit_trend):
            return StrategyDecision(
                action=StrategyAction.EXIT,
                reason="Trend weakening or RSI reset",
                strength=1.0,
                features=features,
            )

        return StrategyDecision(
            action=StrategyAction.HOLD,
            reason="Conditions not aligned",
            strength=self._strength(latest, long_bias=True),
            features=features,
        )

    def _prepare(self, df: pd.DataFrame) -> pd.DataFrame | None:
        if len(df) < max(self.settings.ema_slow + 5, self.settings.history_bars // 4):
            return None
        enriched = df.copy()
        enriched["ema_fast"] = ema(enriched["close"], self.settings.ema_fast)
        enriched["ema_slow"] = ema(enriched["close"], self.settings.ema_slow)
        enriched["rsi"] = rsi(enriched["close"], self.settings.rsi_period)
        enriched["volume_sma"] = enriched["volume"].rolling(self.settings.volume_sma_period).mean()
        enriched.dropna(inplace=True)
        if enriched.empty:
            return None
        return enriched

    def _build_features(self, enriched: pd.DataFrame) -> dict:
        latest = enriched.iloc[-1]
        volume_threshold = latest["volume_sma"] * self.settings.volume_multiplier
        volume_ok = latest["volume"] >= volume_threshold if self.settings.volume_filter_enabled else True
        return {
            "close": float(latest["close"]),
            "ema_fast": float(latest["ema_fast"]),
            "ema_slow": float(latest["ema_slow"]),
            "rsi": float(latest["rsi"]),
            "volume": float(latest["volume"]),
            "volume_sma": float(latest["volume_sma"]),
            "volume_threshold": float(volume_threshold),
            "volume_ok": bool(volume_ok),
        }

    def _strength(self, latest: pd.Series, long_bias: bool) -> float:
        ema_gap = (latest["ema_fast"] - latest["ema_slow"]) / latest["ema_slow"]
        ema_score = max(0.0, min(1.0, ema_gap * (800 if long_bias else -800)))
        rsi_mid = (self.settings.rsi_entry_min + max(self.settings.rsi_entry_max, self.settings.rsi_entry_min + 5)) / 2
        rsi_range = max(2, self.settings.rsi_entry_max - self.settings.rsi_entry_min)
        rsi_score = 1 - min(1.0, abs(latest["rsi"] - rsi_mid) / rsi_range)
        return round(max(0.0, (ema_score + rsi_score) / 2), 3)


class TrendShortStrategy(BaseStrategy):
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
        volatility = self._recent_volatility(enriched)
        volatility_cap = self.settings.volatility_max_pct
        volatility_ok = True if volatility_cap is None else volatility <= volatility_cap
        features = self._build_features(enriched, volatility, volatility_cap)

        in_position = getattr(getattr(state, "open_position", None), "side", None) == "SHORT"
        trend_down = latest["ema_fast"] < latest["ema_slow"]
        rsi_ok = latest["rsi"] <= self.settings.rsi_entry_max
        exit_rsi_level = self.settings.rsi_exit_short or (self.settings.rsi_entry_max + 5)
        exit_rsi = latest["rsi"] >= exit_rsi_level
        exit_trend = latest["ema_fast"] > latest["ema_slow"]

        if trend_down and rsi_ok and not in_position and features["volume_ok"] and volatility_ok:
            return StrategyDecision(
                action=StrategyAction.ENTER_SHORT,
                reason="Downtrend + RSI confirmation",
                strength=self._strength(latest, long_bias=False),
                features=features,
            )

        if in_position and (exit_rsi or exit_trend):
            return StrategyDecision(
                action=StrategyAction.EXIT,
                reason="Short guard triggered",
                strength=1.0,
                features=features,
            )

        hold_reason = "Waiting for short setup" if trend_down else "Trend not bearish"
        if not volatility_ok:
            hold_reason = "Volatility guard active"
        return StrategyDecision(
            action=StrategyAction.HOLD,
            reason=hold_reason,
            strength=self._strength(latest, long_bias=False),
            features=features,
        )

    def _prepare(self, df: pd.DataFrame) -> pd.DataFrame | None:
        if len(df) < max(self.settings.ema_slow + 5, self.settings.history_bars // 4):
            return None
        enriched = df.copy()
        enriched["ema_fast"] = ema(enriched["close"], self.settings.ema_fast)
        enriched["ema_slow"] = ema(enriched["close"], self.settings.ema_slow)
        enriched["rsi"] = rsi(enriched["close"], self.settings.rsi_period)
        enriched["volume_sma"] = enriched["volume"].rolling(self.settings.volume_sma_period).mean()
        enriched.dropna(inplace=True)
        if enriched.empty:
            return None
        return enriched

    def _recent_volatility(self, enriched: pd.DataFrame) -> float:
        pct = enriched["close"].pct_change().abs()
        window = pct.tail(self.settings.volatility_lookback)
        if window.empty:
            return 0.0
        return float(window.max())

    def _build_features(self, enriched: pd.DataFrame, volatility: float, volatility_cap: float | None) -> dict:
        latest = enriched.iloc[-1]
        volume_threshold = latest["volume_sma"] * self.settings.volume_multiplier
        volume_ok = latest["volume"] >= volume_threshold if self.settings.volume_filter_enabled else True
        return {
            "close": float(latest["close"]),
            "ema_fast": float(latest["ema_fast"]),
            "ema_slow": float(latest["ema_slow"]),
            "rsi": float(latest["rsi"]),
            "volume": float(latest["volume"]),
            "volume_sma": float(latest["volume_sma"]),
            "volume_threshold": float(volume_threshold),
            "volume_ok": bool(volume_ok),
            "volatility_pct": float(volatility),
            "volatility_cap": volatility_cap,
        }

    def _strength(self, latest: pd.Series, long_bias: bool) -> float:
        ema_gap = (latest["ema_slow"] - latest["ema_fast"]) / latest["ema_slow"]
        ema_score = max(0.0, min(1.0, ema_gap * 800))
        rsi_mid = (self.settings.rsi_entry_min + self.settings.rsi_entry_max) / 2
        rsi_range = max(2, self.settings.rsi_entry_max - self.settings.rsi_entry_min)
        rsi_score = 1 - min(1.0, abs(latest["rsi"] - rsi_mid) / rsi_range)
        return round(max(0.0, (ema_score + rsi_score) / 2), 3)
