from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import pandas as pd

from ..indicators.ema import ema
from ..indicators.rsi import rsi

SignalType = Literal["BUY", "HOLD", "EXIT"]


@dataclass
class SignalResult:
    timestamp: datetime
    signal: SignalType
    reason: str


class TrendSignalGenerator:
    def __init__(self, log_dir: str = "data/signals"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, df: pd.DataFrame, ema_fast: int, ema_slow: int, rsi_period: int, rsi_min: int, rsi_max: int) -> SignalResult:
        df = df.copy()
        df["ema_fast"] = ema(df["close"], ema_fast)
        df["ema_slow"] = ema(df["close"], ema_slow)
        df["rsi"] = rsi(df["close"], rsi_period)

        latest = df.iloc[-1]
        timestamp = latest["open_time"] if "open_time" in latest else datetime.utcnow()

        if latest["ema_fast"] > latest["ema_slow"] and rsi_min <= latest["rsi"] <= rsi_max:
            signal = "BUY"
            reason = "Trend up + RSI neutral"
        elif latest["ema_fast"] < latest["ema_slow"] or latest["rsi"] < rsi_min:
            signal = "EXIT"
            reason = "Trend down or RSI low"
        else:
            signal = "HOLD"
            reason = "No setup"

        result = SignalResult(timestamp=timestamp, signal=signal, reason=reason)
        self._log_signal(result)
        return result

    def _log_signal(self, result: SignalResult) -> None:
        log_path = self.log_dir / f"signals_{datetime.utcnow():%Y%m%d}.csv"
        header = "timestamp,signal,reason\n"
        line = f"{result.timestamp},{result.signal},{result.reason}\n"
        if not log_path.exists():
            log_path.write_text(header + line, encoding="utf-8")
        else:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(line)
