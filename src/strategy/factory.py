from __future__ import annotations

from ..config.settings import StrategySettings
from .scalper import ScalperStrategy
from .trend import TrendLongStrategy, TrendShortStrategy


def build_strategy(settings: StrategySettings):
    if settings.type == "trend_short":
        return TrendShortStrategy(settings)
    if settings.type == "scalper":
        return ScalperStrategy(settings)
    return TrendLongStrategy(settings)
