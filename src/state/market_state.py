from enum import Enum
import pandas as pd
from ..indicators.ema import ema


class MarketState(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    RANGING = "ranging"


def classify_state(df: pd.DataFrame, fast: int, slow: int) -> MarketState:
    ema_fast = ema(df["close"], fast)
    ema_slow = ema(df["close"], slow)
    if ema_fast.iloc[-1] > ema_slow.iloc[-1]:
        return MarketState.BULLISH
    if ema_fast.iloc[-1] < ema_slow.iloc[-1]:
        return MarketState.BEARISH
    return MarketState.RANGING
