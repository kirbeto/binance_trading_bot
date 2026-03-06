@echo off

echo Starting Binance bots in LIVE mode...

start "TREND BOT" cmd /k python scripts/live_trade.py --config config/trend_bot.yaml --loop --confirm-live I_UNDERSTAND_THE_RISK

start "SHORT BOT" cmd /k python scripts/live_trade.py --config config/short_bot.yaml --loop --confirm-live I_UNDERSTAND_THE_RISK

start "SCALPER BOT" cmd /k python scripts/live_trade.py --config config/scalper_bot.yaml --loop --confirm-live I_UNDERSTAND_THE_RISK

echo All bots started.
pause