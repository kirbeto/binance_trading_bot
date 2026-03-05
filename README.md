# Stable Autonomous Crypto Trading Bot (Binance Spot)

Conservative BTC/USDT spot bot focused on capital preservation, clean execution, and transparent logging. Built for 1-hour candles, paper-trading first, with modular pieces ready for future live deployment.

## Phase 1 Deliverables (current)
- ✅ Configurable YAML + `.env` secrets loader (`config/bot.yaml`, `BINANCE_API_KEY/SECRET`).
- ✅ Binance data feed (1h candles, 300-bar window) feeding EMA/RSI/volume features.
- ✅ Conservative trend strategy (EMA 50/200 trend filter, RSI 14 band, 20-period volume spike confirmation).
- ✅ Risk manager enforcing:
  - 5–15 % dynamic position sizing (strength-weighted).
  - 1.5–3 % stop band (default 2 %).
  - ≥1:1.5 risk-reward TP (default 1.6× stop distance).
  - One position at a time + daily loss cap (default −3 %).
- ✅ Paper-trading executor with persistent state, trade blotter, and structured CSV logs.

## Repo Layout
```
src/
  config/         # YAML loader + typed settings
  data/           # Binance klines wrapper
  strategy/       # EMA/RSI/volume signal logic
  risk/           # Risk guardrails + position planning
  execution/
    state.py      # Account state persistence
    paper.py      # Paper trading loop
scripts/
  paper_trade.py  # CLI entrypoint (one-shot or loop)
config/
  bot.yaml        # Active configuration (copy from bot.example.yaml)
```

## Getting Started
1. **Python environment**
   ```bash
   cd binance_trading_bot
   python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```
2. **Config & secrets**
   - Copy `config/bot.example.yaml` → `config/bot.yaml` (already provided) and edit if needed.
   - Create `.env` (from `.env.example`) with `BINANCE_API_KEY` / `BINANCE_API_SECRET` (read-only keys are fine for data; trading keys required later).
3. **Run paper mode (single evaluation)**
   ```bash
   python scripts/paper_trade.py --config config/bot.yaml
   ```
4. **Continuous loop (dry-run only)**
   ```bash
   python scripts/paper_trade.py --loop
   ```
   The loop sleeps for `app.poll_interval_sec` (default 300 s) between cycles.

Outputs land in `data/paper_trades.csv` (entry/exit events) and `data/paper_blotter.csv` (cycle metrics). State (balance, open position) persists in `data/state/paper_state.json` so stopping/starting retains context.

## Next Steps
- Wire up backtest harness to reuse the new strategy/risk modules.
- Add alerting (Telegram/email) on fills or rule breaches.
- Introduce live execution adapter once paper logs show stability.
- Expand to ETH/USDT after BTC flow is proven.

All live-trading code paths remain disabled until explicitly enabled in configuration.
