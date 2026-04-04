"""
Pelosi Algo Trader — Configuration
===================================
All settings in one place. Adjust these to tune your strategy.
"""

# ── PORTFOLIO SETTINGS ──────────────────────────────────────────────
STARTING_CAPITAL = 500.00          # Your initial capital
MAX_POSITION_SIZE = 100.00         # Max $ per single trade (scale-in approach)
MIN_POSITION_SIZE = 50.00          # Min $ per trade (don't go smaller than this)
MAX_OPEN_POSITIONS = 5             # Max stocks to hold at once
CASH_RESERVE_PCT = 0.10            # Always keep 10% cash as buffer

# ── RISK MANAGEMENT ─────────────────────────────────────────────────
STOP_LOSS_PCT = 0.08               # Sell if position drops 8%
TAKE_PROFIT_PCT = 0.15             # Take profit at 15% gain
TRAILING_STOP_PCT = 0.05           # 5% trailing stop after hitting +10%
TRAILING_STOP_ACTIVATION = 0.10    # Activate trailing stop after 10% gain

# ── SIGNAL SCORING THRESHOLDS ───────────────────────────────────────
MIN_SIGNAL_SCORE = 60              # Only act on signals scoring 60+/100
STRONG_SIGNAL_SCORE = 80           # Strong signal = larger position size

# ── TIMING ──────────────────────────────────────────────────────────
HOLDING_PERIOD_DAYS_MIN = 5        # Min hold = ~1 week
HOLDING_PERIOD_DAYS_MAX = 14       # Max hold = ~2 weeks
DISCLOSURE_DELAY_MAX_DAYS = 45     # Congress has 45 days to disclose
FRESHNESS_WINDOW_DAYS = 90          # Look back 90 days for recent trades

# ── DATA SOURCES ────────────────────────────────────────────────────
QUIVER_QUANT_URL = "https://www.quiverquant.com/congresstrading/"
CAPITOL_TRADES_URL = "https://www.capitoltrades.com/trades"
HOUSE_STOCK_WATCHER_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"
YAHOO_FINANCE_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"

# ── TRACKED POLITICIANS ────────────────────────────────────────────
TRACKED_POLITICIANS = [
    "Nancy Pelosi",
    "Paul Pelosi",       # Trades often filed under Paul (her husband)
]

# ── POSITION SIZING RULES ──────────────────────────────────────────
# Based on signal score, how much of max_position to allocate
POSITION_SIZING = {
    "strong":   1.00,    # Score 80+  → full max position ($100)
    "moderate": 0.70,    # Score 60-79 → 70% of max ($70)
    "weak":     0.00,    # Score <60  → skip
}

# ── SECTOR WEIGHTS (Pelosi tends to favor tech) ─────────────────────
SECTOR_BOOST = {
    "Technology":        1.15,   # 15% score boost for tech
    "Communication Services": 1.10,
    "Consumer Discretionary": 1.05,
    "Healthcare":        1.05,
    "Financials":        1.00,
    "Energy":            0.95,
    "Other":             1.00,
}

# ── FILE PATHS ──────────────────────────────────────────────────────
import os
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolio.json")
TRADES_LOG_FILE = os.path.join(DATA_DIR, "trades_log.json")
SIGNALS_FILE = os.path.join(DATA_DIR, "signals.json")
PERFORMANCE_FILE = os.path.join(DATA_DIR, "performance.json")
