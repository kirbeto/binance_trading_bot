from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator


class AppSettings(BaseModel):
    name: str = Field("trend-bot", pattern=r"^[A-Za-z0-9_-]+$")
    mode: Literal["paper", "live"] = "paper"
    poll_interval_sec: int = Field(300, ge=30, le=3600)
    symbol: str = "BTCUSDT"
    interval: Literal["1m", "3m", "5m", "15m", "1h", "4h", "1d"] = "1h"


class StrategySettings(BaseModel):
    type: Literal["trend_long", "trend_short", "scalper"] = "trend_long"
    ema_fast: int = Field(50, ge=5, le=500)
    ema_slow: int = Field(200, ge=10, le=1000)
    rsi_period: int = Field(14, ge=5, le=50)
    rsi_entry_min: int = Field(35, ge=5, le=95)
    rsi_entry_max: int = Field(65, ge=5, le=95)
    rsi_exit: int = Field(70, ge=5, le=95)
    rsi_exit_short: Optional[int] = Field(default=None, ge=5, le=95)
    rsi_exit_upper: Optional[int] = Field(default=None, ge=5, le=95)
    rsi_exit_lower: Optional[int] = Field(default=None, ge=5, le=95)
    volume_sma_period: int = Field(20, ge=5, le=500)
    volume_multiplier: float = Field(1.0, ge=0.1, le=5.0)
    volume_filter_enabled: bool = False
    volatility_max_pct: Optional[float] = Field(default=None, ge=0.0, le=0.2)
    volatility_lookback: int = Field(5, ge=1, le=50)
    history_bars: int = Field(300, ge=100, le=2000)

    @field_validator("ema_slow")
    @classmethod
    def _ensure_fast_slower(cls, slow: int, info):
        fast = info.data.get("ema_fast", 50)
        if slow <= fast:
            raise ValueError("ema_slow must be greater than ema_fast")
        return slow

    @field_validator("rsi_entry_max")
    @classmethod
    def _validate_rsi_bounds(cls, value: int, info):
        if value <= info.data.get("rsi_entry_min", 35):
            raise ValueError("rsi_entry_max must be greater than rsi_entry_min")
        return value


class RiskSettings(BaseModel):
    starting_capital: float = Field(100.0, gt=0)
    position_pct_min: float = Field(0.05, gt=0, lt=1)
    position_pct_max: float = Field(0.15, gt=0, lt=1)
    stop_loss_pct: float = Field(0.02, gt=0, lt=0.2)
    take_profit_rr: float = Field(1.5, gt=1.0)
    take_profit_pct: Optional[float] = Field(default=None, gt=0, le=0.2)
    daily_loss_cap_pct: float = Field(0.03, gt=0, lt=1)
    max_open_positions: int = Field(1, ge=1, le=3)

    @field_validator("position_pct_max")
    @classmethod
    def _ensure_position_range(cls, max_value: float, info):
        min_value = info.data.get("position_pct_min", 0.05)
        if max_value <= min_value:
            raise ValueError("position_pct_max must be greater than position_pct_min")
        return max_value


class LoggingSettings(BaseModel):
    trade_log: str = "data/paper_trades.csv"
    blotter_log: str = "data/paper_blotter.csv"
    state_file: str = "data/state/paper_state.json"
    signal_log: str = "data/logs/signal_evals.csv"
    live_trade_log: str = "logs/live/trades.csv"
    live_execution_log: str = "logs/live/orders.jsonl"
    live_signal_log: str = "logs/live/signals.csv"
    live_state_file: str = "data/state/live_state.json"


class LiveSettings(BaseModel):
    min_balance: float = Field(100.0, gt=0)
    min_notional: float = Field(10.0, ge=5.0)
    fee_bps: float = Field(10.0, ge=0.0, le=100.0)


class ExecutionSettings(BaseModel):
    market: Literal["spot", "futures"] = "spot"
    margin_mode: Literal["cross", "isolated"] = "cross"
    leverage: float = Field(1.0, ge=1.0, le=20.0)
    trade_side: Literal["long", "short", "both"] = "long"


class Settings(BaseModel):
    app: AppSettings = AppSettings()
    strategy: StrategySettings = StrategySettings()
    risk: RiskSettings = RiskSettings()
    logging: LoggingSettings = LoggingSettings()
    live: LiveSettings = LiveSettings()
    execution: ExecutionSettings = ExecutionSettings()

    def ensure_paths(self) -> None:
        for path_str in [
            self.logging.trade_log,
            self.logging.blotter_log,
            self.logging.state_file,
            self.logging.signal_log,
            self.logging.live_trade_log,
            self.logging.live_execution_log,
            self.logging.live_signal_log,
            self.logging.live_state_file,
        ]:
            path = Path(path_str)
            path.parent.mkdir(parents=True, exist_ok=True)


def load_settings(path: str | Path | None = None) -> Settings:
    config_path = Path(path or os.environ.get("BOT_CONFIG_PATH", "config/bot.yaml"))
    if not config_path.exists():
        example = Path("config/bot.example.yaml").resolve()
        raise FileNotFoundError(
            f"Config file '{config_path}' not found. Copy '{example}' to '{config_path}' and adjust your settings."
        )

    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    settings = Settings(**raw)
    settings.ensure_paths()
    return settings
