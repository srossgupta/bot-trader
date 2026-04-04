# Bot Trader

Congressional trade-following algo that tracks Nancy Pelosi's stock trades and generates buy/sell signals.

## How It Works

1. Scrapes Pelosi family trade disclosures from [CapitolTrades](https://www.capitoltrades.com)
2. Scores each trade on a 0-100 scale (freshness, size, momentum, volume, sector, repeat signals)
3. Sell signals are weighted more heavily — backtest shows Pelosi's sells are the strongest alpha
4. Conflicting signals (bought AND sold same ticker) are resolved in favor of the higher-scoring direction
5. Generates actionable recommendations with position sizing for a $500 paper trading account

## Setup

```bash
pip install -r requirements.txt
```

Requires Python 3.10+. Dependencies: `requests`, `beautifulsoup4`.

## Usage

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
