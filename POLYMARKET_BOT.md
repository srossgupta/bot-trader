# Polymarket Bot (Paper Trading)

This repo now includes a dedicated Polymarket paper-trading engine in `polymarket_bot/`.

## Strategy Implemented

- Universe: all active Polymarket markets, excluding crypto-related markets.
- Daily scan: at a fixed local time (`scan_hour_local`, `scan_minute_local`).
- Window: markets ending in next 24 hours.
- Wake logic: wake at `T - wake_minutes_before_close` (default `T-6`).
- Liquidity filter: only track markets with volume `>= $100,000`.
- Entry: if YES or NO reaches `>= 95c`, place paper limit buy on that side.
- Position sizing: max `$100` per market.
- Stop-loss: if held side drops below `70c`, paper market-sell.
- Expiry handling: force-close any open position at latest observed price near close.

## Self-Correcting Loop

After closed trades accumulate, the bot auto-adjusts:

- `entry_threshold_cents`
- `stop_loss_cents`
- `wake_minutes_before_close`

It also tracks category-level expectancy and stores preferred categories for future scans.

Adaptive state persists in:

- `data/polymarket/adaptive_state.json`

## Commands

```bash
# Backtest (uses recorded snapshots, else synthetic bootstrap)
python run_polymarket.py --backtest

# Run one full daily cycle now (scan + monitor + adaptation)
python run_polymarket.py --paper-once

# Run forever on fixed daily schedule
python run_polymarket.py --run-loop
```

## Logs and Data

- Watchlist: `data/polymarket/watchlist.json`
- Price snapshots: `data/polymarket/price_snapshots.jsonl`
- Trade ledger: `data/polymarket/paper_trades.jsonl`
- Metrics history: `data/polymarket/metrics_history.jsonl`

These logs are designed so you can quickly re-evaluate P&L when changing parameters (e.g., T-6 to T-15, or different entry/stop thresholds).

## Notes

- This is paper trading only.
- No real order placement is performed.
- Network/API availability is required for live scanning and price pulls.
