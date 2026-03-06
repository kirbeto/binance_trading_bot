# Multi-Bot Binance Trading Framework

Modular BTCUSDT trading stack designed to run several strategy profiles in parallel (trend-following long, trend-following short, and fast scalper). Each bot uses its own config, state, and logs so they can safely share the same account without conflicting order/state management. The default runtime is paper mode for validation; wiring to live endpoints can be layered on later.

## Key Capabilities
- ✅ Typed YAML configs per bot (`config/<bot>.yaml`) with isolated logs/state paths.
- ✅ Strategy factory supporting:
  - **Trend Bot (long only)** – EMA50/EMA200 + RSI filter.
  - **Short Bot (short only, 3× futures leverage)** – EMA50/EMA200 bearish confirmation + volatility guard.
  - **Scalper Bot (bi-directional)** – EMA9/EMA21 crossovers inside RSI band for low-volatility chops.
- ✅ Unified risk manager that understands margin, leverage, isolated/cross mode, and direction-specific stops/take-profit targets.
- ✅ Paper execution engine with per-bot CSV trade blotters, JSON state, and signal logs (features captured as JSON for easy downstream analysis).
- ✅ Multi-bot runner (`scripts/run_bots.py`) to spin up any number of configs concurrently in separate threads.

## Repo Layout
```
src/
  config/          # Settings models + loader
  data/            # Binance klines wrapper
  execution/       # Paper executor + state persistence
  indicators/      # EMA/RSI helpers
  risk/            # Position sizing + guardrails
  strategy/        # Trend + scalper strategies + factory
scripts/
  paper_trade.py   # Run a single bot (one-shot or loop)
  run_bots.py      # Run multiple configs in parallel
config/
  bot.example.yaml # Template
  trend_bot.yaml   # LONG trend profile
  short_bot.yaml   # SHORT futures profile
  scalper_bot.yaml # Fast crossover profile
```

## Getting Started
1. **Environment**
   ```bash
   cd binance_trading_bot
   python -m venv .venv && source .venv/bin/activate   # on Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. **Secrets**
   - Copy `.env.example` → `.env` and add `BINANCE_API_KEY` / `BINANCE_API_SECRET` (read-only ok for paper mode).
3. **Choose configs**
   - Use the provided `config/*_bot.yaml` files or copy `config/bot.example.yaml` to create new profiles.
   - Each config defines: `app` metadata, strategy type, leverage/margin settings, and dedicated log/state paths.
4. **Run a single bot**
   ```bash
   python scripts/paper_trade.py --config config/trend_bot.yaml --loop
   ```
5. **Run three bots together**
   ```bash
   python scripts/run_bots.py --configs \
       config/trend_bot.yaml \
       config/short_bot.yaml \
       config/scalper_bot.yaml
   ```
   Each bot reports with its own `[bot-name]` prefix and writes to its isolated CSV/JSON files.

Outputs per bot:
- `logs/<bot>/trades.csv` – entry/exit tape with PnL, side, duration.
- `logs/<bot>/signals.csv` – strategy decisions + JSON-encoded feature snapshot.
- `logs/<bot>/blotter.csv` – cycle-level telemetry.
- `data/state/<bot>.json` – persistent account state (balance, open position).

## Next Steps
- Backtest harness that reuses the strategy/risk stack for offline validation.
- Alerting hooks (Telegram/email) for fills and guard-rails.
- Live execution adapters for Binance Spot + Futures using the same config schema.
- Additional symbols/portfolios once BTCUSDT flows are verified.

> **Safety note:** Live trading is disabled by default. Keep paper mode on until you review logs, validate risk, and wire real executors.
