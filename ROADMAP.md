# Roadmap: Stable Autonomous Binance Spot Bot

## Phase 1 – Observation Only
- `src/data/historical_fetcher.py`: download BTC/USDT OHLCV (15m, 1h)
- `src/indicators/ema.py`, `src/indicators/rsi.py`
- `src/state/market_state.py`: classify bullish/bearish/ranging
- CLI script `scripts/observe.py` that prints indicator snapshot (no trades)

## Phase 2 – Signal Generation
- `src/signals/trend_signal.py`: apply EMA filter + RSI band logic
- Logging into `data/signals/*.csv` with timestamp + reason

## Phase 3 – Backtesting
- `src/backtest/engine.py`: iterate signals, apply TP/SL rules
- Metrics output: win rate, max drawdown, expectancy, trade count

## Phase 4 – Risk Management
- `src/risk/position_sizer.py`: 1-2% capital risk & single-position guard
- Safety rule: stop after X consecutive losses

## Phase 5 – Paper Trading
- `src/execution/paper_trader.py`: virtual orders with Binance market data feed

## Phase 6 – Live Trading
- `src/execution/live_trader.py`: real orders (same logic) + alert hooks

## Phase 7 – Iterative Improvements
- Document backlog for adding extra filters/pairs once stable
