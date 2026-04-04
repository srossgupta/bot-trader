# Pelosi Algo Trader — Strategy Guide

## What This Does

This system tracks Nancy Pelosi's stock trades (filed as public disclosures), scores them, and tells you exactly what to buy or sell on Robinhood — and how much.

You start with **$500** and scale in gradually ($50–$100 per trade).

---

## How the Strategy Works

### The Edge
Members of Congress must publicly disclose their stock trades. Research shows these trades — especially Pelosi's — tend to outperform the market. The key insight: if someone with access to legislative intel is buying a stock with millions of dollars, that's a strong signal.

### The Challenge
There's a **disclosure delay** (up to 45 days). By the time we see the trade, some of the move may have happened already. Our scoring system accounts for this — fresher disclosures score higher.

### Signal Scoring (0–100 points)

Each Pelosi trade gets scored on 6 factors:

| Factor | Max Points | What It Measures |
|--------|-----------|-----------------|
| Freshness | 20 | How recently was it disclosed? (fresher = better) |
| Trade Size | 20 | How much did Pelosi trade? ($5M+ = max conviction) |
| Momentum | 20 | Is the stock trending the right direction? |
| Volume | 15 | Is there unusual trading activity? |
| 52-Week Position | 10 | Where is the price in its yearly range? |
| Repeat Signal | 15 | Has Pelosi traded this ticker multiple times? |

A sector multiplier adjusts the final score (tech gets a 15% boost since that's Pelosi's strong suit).

**Score 80+ = STRONG BUY → $100 position**
**Score 60–79 = BUY → $70 position**
**Score <60 = SKIP**

### Risk Management

- **8% stop loss** — auto-suggests selling if a position drops 8%
- **15% take profit** — locks in gains at 15%
- **5% trailing stop** — after a position is up 10%, it trails 5% below the peak
- **Max 5 positions** at once
- **10% cash reserve** always maintained
- **2-week max hold** — the system flags positions held too long

---

## How to Use It

### Setup (one time)
```bash
cd pelosi_trader
pip install -r requirements.txt
```

### Daily Commands

```bash
# Full daily scan — fetches Pelosi trades, scores them, checks your positions
python run.py

# Just check your portfolio status
python run.py --status

# See latest Pelosi signals without portfolio context
python run.py --signals

# View your performance over time
python run.py --history

# Quick backtest on recent signals
python run.py --backtest

# Reset portfolio back to $500
python run.py --reset
```

### Your Daily Routine

1. **Morning (before market open):** Run `python run.py`
2. **Read the output** — it tells you exactly what to do:
   - "BUY 1.5 shares of NVDA at ~$130 on Robinhood"
   - "SELL your AAPL position (stop loss hit)"
3. **Place the trades manually on Robinhood**
4. **That's it.** The system tracks everything.

---

## How It Optimizes Over Time

After you've closed at least 3 trades, the system starts analyzing what's working:

- **Win rate tracking** — are more trades winning than losing?
- **Score calibration** — if high-score trades win more, it suggests being more selective
- **Risk tuning** — if losses are too big vs wins, it suggests tighter stop losses
- **Sector analysis** — tracks which sectors perform best for Pelosi signals

These suggestions appear automatically in the "Strategy Health Check" section of your daily run.

---

## File Structure

```
pelosi_trader/
├── run.py              ← Main script (run this daily)
├── config.py           ← All settings (edit to tune strategy)
├── data_fetcher.py     ← Pulls trade data & stock prices
├── signal_scorer.py    ← Scores each signal 0-100
├── portfolio_manager.py← Tracks positions, risk, P&L
├── daily_monitor.py    ← Daily monitoring & optimization brain
├── requirements.txt    ← Python dependencies
├── STRATEGY_GUIDE.md   ← This file
└── data/
    ├── portfolio.json     ← Your portfolio state (auto-created)
    ├── trades_log.json    ← History of all trades (auto-created)
    ├── performance.json   ← Daily performance snapshots (auto-created)
    └── sample_trades.json ← Demo data
```

---

## Config You Can Tweak

Open `config.py` to adjust:

- `STARTING_CAPITAL` — change from $500 if needed
- `MAX_POSITION_SIZE` — increase as strategy proves itself
- `STOP_LOSS_PCT` — tighten (0.05) or loosen (0.10)
- `MIN_SIGNAL_SCORE` — raise to be more selective
- `HOLDING_PERIOD_DAYS_MAX` — change from 14 days

---

## Future Upgrade: Auto-Execution

If you want true auto-trading later, sign up for **Alpaca** (free, has a real trading API). The system is designed to easily plug into Alpaca's API — just swap the `open_position` and `close_position` functions in `portfolio_manager.py` to make real API calls instead of logging.

---

## Important Disclaimer

This is a tool for educational and personal use. It is not financial advice. Congressional trade data has inherent delays and limitations. Past performance doesn't guarantee future results. Only trade with money you can afford to lose.
