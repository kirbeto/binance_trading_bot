from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Optional

import pandas as pd


class StrategyAction(str, Enum):
    ENTER_LONG = "ENTER_LONG"
    ENTER_SHORT = "ENTER_SHORT"
    EXIT = "EXIT"
    HOLD = "HOLD"


@dataclass
class StrategyDecision:
    action: StrategyAction
    reason: str
    strength: float
    features: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["action"] = self.action.value
        return payload


class BaseStrategy(ABC):
    """Interface every trading strategy must implement."""

    @abstractmethod
    def evaluate(self, market_data: pd.DataFrame, state: Optional[Any] = None) -> StrategyDecision:
        """Produce a decision for the provided market data snapshot."""
        raise NotImplementedError
