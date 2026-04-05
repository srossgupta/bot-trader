# Bot Trader

Congressional trade-following algo that tracks Nancy Pelosi's stock trades and generates buy/sell signals.

## Polymarket Paper Bot

For the new Polymarket strategy bot (paper trading, backtesting, adaptive tuning), see `POLYMARKET_BOT.md` and run:

```bash
python run_polymarket.py --backtest
python run_polymarket.py --paper-once
python run_polymarket.py --run-loop
```

## How It Works

1. Scrapes Pelosi family trade disclosures from [CapitolTrades](https://www.capitoltrades.com)
2. Scores each trade on a 0-100 scale (freshness, size, momentum, volume, sector, repeat signals)
3. Sell signals are weighted more heavily — backtest shows Pelosi's sells are the strongest alpha
4. Conflicting signals (bought AND sold same ticker) are resolved in favor of the higher-scoring direction
5. Generates actionable recommendations with position sizing for a $500 paper trading account

## Setup

**Requirements:** Python 3.10+

```bash
# 1. Clone the repo
git clone https://github.com/srossgupta/bot-trader.git
cd bot-trader

# 2. Install dependencies
pip install -r requirements.txt
```

## Running the Web Dashboard

The easiest way to use the app — open a browser UI with signals, backtest, and portfolio.

```bash
python app.py
```

Then open **http://localhost:5050** in your browser.

The dashboard shows:
- Portfolio value and return at a glance
- All Pelosi signals scored and ranked (with conflict detection)
- New trade alerts when she files a fresh disclosure
- One-click backtest with actual returns vs SPY benchmark
- Performance history over time

## Running from the Command Line

```bash
# Daily scan — shows buy/sell recommendations
python run.py

# Show latest scored signals
python run.py --signals

# Portfolio status
python run.py --status

# Backtest — actual returns from Pelosi's trade dates
python run.py --backtest

# Performance history over time
python run.py --history

# Reset portfolio to starting capital
python run.py --reset
```

## Running Daily (Recommended)

Run `python run.py` once a day. It will alert you with a `🚨 NEW PELOSI TRADES DETECTED` banner whenever she files a new disclosure — quiet days will just say "no new trades since last check."

To automate, add a cron job:
```bash
# Run every morning at 9am
0 9 * * * cd /path/to/bot-trader && python run.py >> data/daily.log 2>&1
```

## Configuration

Edit `config.py` to tune the strategy:

| Setting | Default | Description |
|---|---|---|
| `STARTING_CAPITAL` | $500 | Paper trading budget |
| `MAX_POSITION_SIZE` | $100 | Max per trade |
| `MIN_SIGNAL_SCORE` | 60 | Threshold for buy signals (sells use 45) |
| `STOP_LOSS_PCT` | 8% | Auto-sell if position drops 8% |
| `TAKE_PROFIT_PCT` | 15% | Take profit at 15% gain |
| `FRESHNESS_WINDOW_DAYS` | 90 | How far back to look for trades |

## Data Sources

- **Trade disclosures**: [CapitolTrades](https://www.capitoltrades.com) (scraped HTML)
- **Stock prices**: Yahoo Finance API
- **Fallback**: Local cached data / sample data if sources are unavailable

## Disclaimer

This is for educational and research purposes only. Not financial advice. Congressional trade data has a disclosure delay of up to 45 days.
