"""
Pelosi Algo Trader — Portfolio Manager
========================================
Tracks positions, manages risk, and decides position sizing.
Persists portfolio state to JSON so it survives restarts.
"""

import json
import os
from datetime import datetime
from typing import Optional

from config import (
    STARTING_CAPITAL,
    MAX_POSITION_SIZE,
    MIN_POSITION_SIZE,
    MAX_OPEN_POSITIONS,
    CASH_RESERVE_PCT,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    TRAILING_STOP_PCT,
    TRAILING_STOP_ACTIVATION,
    STRONG_SIGNAL_SCORE,
    POSITION_SIZING,
    PORTFOLIO_FILE,
    TRADES_LOG_FILE,
    DATA_DIR,
)


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


# ── PORTFOLIO STATE ────────────────────────────────────────────────

def load_portfolio() -> dict:
    """Load portfolio from disk, or create a fresh one."""
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE) as f:
            return json.load(f)

    # Fresh portfolio
    return {
        "cash": STARTING_CAPITAL,
        "starting_capital": STARTING_CAPITAL,
        "positions": {},      # ticker -> position dict
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }


def save_portfolio(portfolio: dict):
    """Save portfolio state to disk."""
    ensure_data_dir()
    portfolio["updated_at"] = datetime.now().isoformat()
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(portfolio, f, indent=2, default=str)


def log_trade(trade_record: dict):
    """Append a trade to the trade log."""
    ensure_data_dir()
    log = []
    if os.path.exists(TRADES_LOG_FILE):
        with open(TRADES_LOG_FILE) as f:
            log = json.load(f)
    log.append(trade_record)
    with open(TRADES_LOG_FILE, "w") as f:
        json.dump(log, f, indent=2, default=str)


# ── POSITION SIZING ───────────────────────────────────────────────

def calculate_position_size(signal_score: float, portfolio: dict) -> float:
    """
    Determine how many dollars to allocate to this trade.

    Rules:
    - Score 80+ (strong) → full max position
    - Score 60-79 (moderate) → 70% of max
    - Score <60 → skip (return 0)
    - Never exceed available cash minus reserve
    - Never go below min position size
    """
    if signal_score >= STRONG_SIGNAL_SCORE:
        size_pct = POSITION_SIZING["strong"]
    elif signal_score >= 60:
        size_pct = POSITION_SIZING["moderate"]
    else:
        return 0  # Signal too weak

    raw_size = MAX_POSITION_SIZE * size_pct

    # Check cash constraints
    available = portfolio["cash"] * (1 - CASH_RESERVE_PCT)
    size = min(raw_size, available)

    if size < MIN_POSITION_SIZE:
        return 0  # Not enough cash for a meaningful position

    return round(size, 2)


# ── TRADE EXECUTION (SIMULATED) ───────────────────────────────────

def open_position(portfolio: dict, ticker: str, price: float,
                  dollars: float, signal_score: float, reason: str) -> dict:
    """
    Open a new position (or add to existing).
    Returns the updated portfolio.
    """
    if ticker in portfolio["positions"]:
        print(f"   ⚠️  Already holding {ticker}, skipping duplicate")
        return portfolio

    if len(portfolio["positions"]) >= MAX_OPEN_POSITIONS:
        print(f"   ⚠️  Max {MAX_OPEN_POSITIONS} positions reached, skipping {ticker}")
        return portfolio

    shares = dollars / price
    cost_basis = price

    position = {
        "ticker": ticker,
        "shares": round(shares, 4),
        "cost_basis": round(cost_basis, 2),
        "dollars_in": round(dollars, 2),
        "entry_date": datetime.now().isoformat(),
        "signal_score": signal_score,
        "stop_loss": round(price * (1 - STOP_LOSS_PCT), 2),
        "take_profit": round(price * (1 + TAKE_PROFIT_PCT), 2),
        "trailing_stop": None,  # Activated later
        "highest_price": price,
        "reason": reason,
    }

    portfolio["positions"][ticker] = position
    portfolio["cash"] = round(portfolio["cash"] - dollars, 2)

    trade_log = {
        "action": "BUY",
        "ticker": ticker,
        "shares": position["shares"],
        "price": price,
        "dollars": dollars,
        "date": datetime.now().isoformat(),
        "signal_score": signal_score,
        "portfolio_cash_after": portfolio["cash"],
        "reason": reason,
    }
    log_trade(trade_log)
    save_portfolio(portfolio)

    print(f"   🟢 OPENED: {shares:.2f} shares of {ticker} @ ${price:.2f} (${dollars:.2f})")
    return portfolio


def close_position(portfolio: dict, ticker: str, current_price: float,
                   reason: str) -> dict:
    """
    Close an existing position.
    Returns the updated portfolio.
    """
    if ticker not in portfolio["positions"]:
        print(f"   ⚠️  No position in {ticker} to close")
        return portfolio

    pos = portfolio["positions"][ticker]
    proceeds = pos["shares"] * current_price
    pnl = proceeds - pos["dollars_in"]
    pnl_pct = (pnl / pos["dollars_in"]) * 100

    portfolio["cash"] = round(portfolio["cash"] + proceeds, 2)
    del portfolio["positions"][ticker]

    trade_log = {
        "action": "SELL",
        "ticker": ticker,
        "shares": pos["shares"],
        "price": current_price,
        "dollars": round(proceeds, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "date": datetime.now().isoformat(),
        "entry_date": pos["entry_date"],
        "reason": reason,
        "portfolio_cash_after": portfolio["cash"],
    }
    log_trade(trade_log)
    save_portfolio(portfolio)

    emoji = "🟢" if pnl >= 0 else "🔴"
    print(f"   {emoji} CLOSED: {ticker} @ ${current_price:.2f} | P&L: ${pnl:.2f} ({pnl_pct:+.1f}%) | Reason: {reason}")
    return portfolio


# ── RISK CHECKS (run daily) ───────────────────────────────────────

def check_stop_loss(portfolio: dict, ticker: str, current_price: float) -> Optional[str]:
    """Check if stop loss has been hit."""
    pos = portfolio["positions"].get(ticker)
    if not pos:
        return None
    if current_price <= pos["stop_loss"]:
        return f"Stop loss hit (${pos['stop_loss']:.2f})"
    return None


def check_take_profit(portfolio: dict, ticker: str, current_price: float) -> Optional[str]:
    """Check if take profit has been hit."""
    pos = portfolio["positions"].get(ticker)
    if not pos:
        return None
    if current_price >= pos["take_profit"]:
        return f"Take profit hit (${pos['take_profit']:.2f})"
    return None


def update_trailing_stop(portfolio: dict, ticker: str, current_price: float) -> Optional[str]:
    """
    Update trailing stop if price has risen enough.
    Returns close reason if trailing stop triggered, None otherwise.
    """
    pos = portfolio["positions"].get(ticker)
    if not pos:
        return None

    gain_pct = (current_price - pos["cost_basis"]) / pos["cost_basis"]

    # Update highest price
    if current_price > pos.get("highest_price", 0):
        pos["highest_price"] = current_price

    # Activate trailing stop once we're up enough
    if gain_pct >= TRAILING_STOP_ACTIVATION:
        trailing_stop_price = pos["highest_price"] * (1 - TRAILING_STOP_PCT)
        pos["trailing_stop"] = round(trailing_stop_price, 2)

        # Check if trailing stop is hit
        if current_price <= pos["trailing_stop"]:
            return f"Trailing stop hit (${pos['trailing_stop']:.2f}, highest was ${pos['highest_price']:.2f})"

    save_portfolio(portfolio)
    return None


def run_risk_checks(portfolio: dict, prices: dict) -> list[dict]:
    """
    Run all risk checks on current positions.
    Returns list of actions to take: [{"ticker": ..., "action": "CLOSE", "reason": ...}]
    """
    actions = []

    for ticker, pos in list(portfolio["positions"].items()):
        price_data = prices.get(ticker)
        if not price_data:
            continue

        current_price = price_data["current_price"]

        # Check stop loss
        reason = check_stop_loss(portfolio, ticker, current_price)
        if reason:
            actions.append({"ticker": ticker, "action": "CLOSE", "reason": reason})
            continue

        # Check take profit
        reason = check_take_profit(portfolio, ticker, current_price)
        if reason:
            actions.append({"ticker": ticker, "action": "CLOSE", "reason": reason})
            continue

        # Check trailing stop
        reason = update_trailing_stop(portfolio, ticker, current_price)
        if reason:
            actions.append({"ticker": ticker, "action": "CLOSE", "reason": reason})
            continue

    return actions


# ── PORTFOLIO SUMMARY ─────────────────────────────────────────────

def get_portfolio_summary(portfolio: dict, prices: dict) -> dict:
    """
    Calculate current portfolio value and performance.
    """
    total_position_value = 0
    positions_detail = []

    for ticker, pos in portfolio["positions"].items():
        price_data = prices.get(ticker)
        if price_data:
            current_price = price_data["current_price"]
        else:
            current_price = pos["cost_basis"]  # Fallback

        current_value = pos["shares"] * current_price
        pnl = current_value - pos["dollars_in"]
        pnl_pct = (pnl / pos["dollars_in"]) * 100

        total_position_value += current_value
        positions_detail.append({
            "ticker": ticker,
            "shares": pos["shares"],
            "cost_basis": pos["cost_basis"],
            "current_price": current_price,
            "current_value": round(current_value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "entry_date": pos["entry_date"],
            "stop_loss": pos["stop_loss"],
            "take_profit": pos["take_profit"],
        })

    total_value = portfolio["cash"] + total_position_value
    total_return = total_value - portfolio["starting_capital"]
    total_return_pct = (total_return / portfolio["starting_capital"]) * 100

    return {
        "cash": round(portfolio["cash"], 2),
        "positions_value": round(total_position_value, 2),
        "total_value": round(total_value, 2),
        "total_return": round(total_return, 2),
        "total_return_pct": round(total_return_pct, 2),
        "num_positions": len(portfolio["positions"]),
        "positions": positions_detail,
    }


def print_portfolio_summary(summary: dict):
    """Pretty-print the portfolio summary."""
    print(f"\n{'='*60}")
    print(f"  📊 PORTFOLIO SUMMARY")
    print(f"{'='*60}")
    print(f"  💵 Cash:           ${summary['cash']:>10,.2f}")
    print(f"  📈 Positions:      ${summary['positions_value']:>10,.2f}")
    print(f"  💰 Total Value:    ${summary['total_value']:>10,.2f}")

    emoji = "🟢" if summary['total_return'] >= 0 else "🔴"
    print(f"  {emoji} Total Return:   ${summary['total_return']:>10,.2f} ({summary['total_return_pct']:+.1f}%)")
    print(f"  📦 Open Positions: {summary['num_positions']}")

    if summary["positions"]:
        print(f"\n  {'Ticker':<8} {'Shares':<8} {'Entry':<8} {'Now':<8} {'P&L':>10} {'%':>8}")
        print(f"  {'-'*52}")
        for p in summary["positions"]:
            emoji = "🟢" if p["pnl"] >= 0 else "🔴"
            print(f"  {p['ticker']:<8} {p['shares']:<8.2f} ${p['cost_basis']:<7.2f} ${p['current_price']:<7.2f} {emoji}${p['pnl']:>8.2f} {p['pnl_pct']:>+7.1f}%")

    print(f"{'='*60}\n")
