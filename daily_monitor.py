"""
Pelosi Algo Trader — Daily Monitor & Optimizer
================================================
Runs daily to:
1. Check for new Pelosi trade disclosures
2. Monitor existing positions (risk checks)
3. Generate new trade signals
4. Track performance and optimize strategy over time

This is the brain that learns and adapts.
"""

import json
import os
from datetime import datetime, timedelta

from config import (
    DATA_DIR,
    PERFORMANCE_FILE,
    HOLDING_PERIOD_DAYS_MAX,
    MIN_SIGNAL_SCORE,
)
from data_fetcher import get_pelosi_signals, fetch_prices_for_tickers
from signal_scorer import rank_signals, get_actionable_signals
from portfolio_manager import (
    load_portfolio,
    save_portfolio,
    open_position,
    close_position,
    run_risk_checks,
    get_portfolio_summary,
    print_portfolio_summary,
    calculate_position_size,
)


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


# ── PERFORMANCE TRACKING ──────────────────────────────────────────

def load_performance_history() -> list[dict]:
    """Load daily performance snapshots."""
    if os.path.exists(PERFORMANCE_FILE):
        with open(PERFORMANCE_FILE) as f:
            return json.load(f)
    return []


def save_performance_snapshot(summary: dict):
    """Save today's portfolio snapshot for tracking over time."""
    ensure_data_dir()
    history = load_performance_history()

    snapshot = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_value": summary["total_value"],
        "cash": summary["cash"],
        "positions_value": summary["positions_value"],
        "total_return_pct": summary["total_return_pct"],
        "num_positions": summary["num_positions"],
    }

    # Don't duplicate today's entry
    history = [h for h in history if h["date"] != snapshot["date"]]
    history.append(snapshot)
    history.sort(key=lambda h: h["date"])

    with open(PERFORMANCE_FILE, "w") as f:
        json.dump(history, f, indent=2)


# ── STRATEGY OPTIMIZER ─────────────────────────────────────────────

def analyze_past_trades() -> dict:
    """
    Look at closed trades to understand what's working and what's not.
    Returns optimization hints.
    """
    from config import TRADES_LOG_FILE
    if not os.path.exists(TRADES_LOG_FILE):
        return {"message": "No trade history yet — need more data to optimize."}

    with open(TRADES_LOG_FILE) as f:
        trades = json.load(f)

    sells = [t for t in trades if t.get("action") == "SELL"]
    if len(sells) < 3:
        return {"message": f"Only {len(sells)} closed trades — need at least 3 to optimize."}

    # Analyze wins vs losses
    wins = [t for t in sells if t.get("pnl", 0) > 0]
    losses = [t for t in sells if t.get("pnl", 0) <= 0]

    avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
    win_rate = len(wins) / len(sells) * 100

    # Check which signal scores led to wins
    winning_scores = [t.get("signal_score", 0) for t in wins]
    losing_scores = [t.get("signal_score", 0) for t in losses]
    avg_winning_score = sum(winning_scores) / len(winning_scores) if winning_scores else 0
    avg_losing_score = sum(losing_scores) / len(losing_scores) if losing_scores else 0

    hints = {
        "total_closed_trades": len(sells),
        "win_rate": round(win_rate, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "avg_winning_score": round(avg_winning_score, 1),
        "avg_losing_score": round(avg_losing_score, 1),
        "suggestions": [],
    }

    # Generate optimization suggestions
    if win_rate < 50:
        hints["suggestions"].append(
            f"Win rate is {win_rate:.0f}%. Consider raising MIN_SIGNAL_SCORE "
            f"from {MIN_SIGNAL_SCORE} to {int(avg_winning_score)} to filter out weaker signals."
        )

    if avg_loss and abs(avg_loss) > avg_win * 1.5:
        hints["suggestions"].append(
            "Average loss is much larger than average win. Consider tightening "
            "STOP_LOSS_PCT to cut losers faster."
        )

    if avg_winning_score > avg_losing_score + 10:
        hints["suggestions"].append(
            f"Winning trades average score {avg_winning_score:.0f} vs "
            f"losing trades {avg_losing_score:.0f}. Higher-scored signals are working — "
            f"consider being more selective."
        )

    if not hints["suggestions"]:
        hints["suggestions"].append("Strategy looks solid so far! Keep monitoring.")

    return hints


# ── HOLDING PERIOD CHECK ──────────────────────────────────────────

def check_holding_periods(portfolio: dict) -> list[dict]:
    """
    Check if any positions have exceeded the max holding period.
    Returns list of tickers to consider closing.
    """
    actions = []
    for ticker, pos in portfolio["positions"].items():
        entry_date = datetime.fromisoformat(pos["entry_date"])
        days_held = (datetime.now() - entry_date).days

        if days_held >= HOLDING_PERIOD_DAYS_MAX:
            actions.append({
                "ticker": ticker,
                "action": "REVIEW",
                "reason": f"Held for {days_held} days (max is {HOLDING_PERIOD_DAYS_MAX})",
                "days_held": days_held,
            })

    return actions


# ── MAIN DAILY RUN ────────────────────────────────────────────────

def daily_run(auto_execute: bool = False):
    """
    Main daily monitoring loop.

    If auto_execute=False (default): prints recommendations only.
    If auto_execute=True: automatically opens/closes positions.
    """
    print(f"\n{'🔄'*30}")
    print(f"  PELOSI ALGO TRADER — Daily Run")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'🔄'*30}\n")

    # 1. Load current portfolio
    portfolio = load_portfolio()
    print(f"📂 Portfolio loaded: ${portfolio['cash']:.2f} cash, "
          f"{len(portfolio['positions'])} positions\n")

    # 2. Fetch new Pelosi signals
    print("── STEP 1: Fetch Pelosi Trades ──")
    signals = get_pelosi_signals()

    # 3. Score and rank signals
    print("\n── STEP 2: Score & Rank Signals ──")
    actionable = get_actionable_signals(signals)
    print(f"   📊 {len(actionable)} signals above threshold (score ≥ {MIN_SIGNAL_SCORE})")

    if actionable:
        print(f"\n   {'Rank':<5} {'Action':<6} {'Ticker':<8} {'Score':<7} {'Recommendation':<15}")
        print(f"   {'-'*45}")
        for i, s in enumerate(actionable[:10], 1):
            print(f"   {i:<5} {s['action']:<6} {s['ticker']:<8} {s['score']:<7.0f} {s['recommendation']}")

    # 4. Get current prices for held positions
    print("\n── STEP 3: Monitor Positions ──")
    held_tickers = list(portfolio["positions"].keys())
    if held_tickers:
        print(f"   Checking prices for {len(held_tickers)} held positions...")
        held_prices = fetch_prices_for_tickers(held_tickers)

        # Run risk checks
        risk_actions = run_risk_checks(portfolio, held_prices)
        if risk_actions:
            print(f"\n   ⚠️  RISK ALERTS:")
            for ra in risk_actions:
                print(f"      {ra['ticker']}: {ra['reason']}")
                if auto_execute:
                    price = held_prices[ra["ticker"]]["current_price"]
                    portfolio = close_position(portfolio, ra["ticker"], price, ra["reason"])

        # Check holding periods
        period_actions = check_holding_periods(portfolio)
        if period_actions:
            print(f"\n   ⏰ HOLDING PERIOD ALERTS:")
            for pa in period_actions:
                print(f"      {pa['ticker']}: {pa['reason']}")
                if auto_execute and pa["days_held"] > HOLDING_PERIOD_DAYS_MAX + 3:
                    # Auto-close if significantly overdue
                    if pa["ticker"] in held_prices:
                        price = held_prices[pa["ticker"]]["current_price"]
                        portfolio = close_position(portfolio, pa["ticker"], price,
                                                   f"Max holding period exceeded ({pa['days_held']}d)")
    else:
        held_prices = {}
        print("   No open positions to monitor.")

    # 5. Process new BUY signals
    #    Suppress buys where a higher-scoring sell exists for the same ticker
    print("\n── STEP 4: New Trade Opportunities ──")
    sell_tickers = {}
    for s in actionable:
        if s["action"] == "SELL":
            sell_tickers[s["ticker"]] = max(sell_tickers.get(s["ticker"], 0), s["score"])

    buy_signals = [s for s in actionable if s["action"] == "BUY"
                   and s["ticker"] not in portfolio["positions"]
                   and s["score"] > sell_tickers.get(s["ticker"], 0)]

    if buy_signals:
        for signal in buy_signals[:3]:  # Top 3 only
            size = calculate_position_size(signal["score"], portfolio)
            if size > 0 and signal.get("price_data"):
                price = signal["price_data"]["current_price"]
                shares = size / price
                print(f"\n   💡 SIGNAL: BUY {signal['ticker']}")
                print(f"      Score: {signal['score']}/100 | Rec: {signal['recommendation']}")
                print(f"      Price: ${price:.2f} | Position: ${size:.2f} ({shares:.2f} shares)")
                print(f"      Pelosi's trade: ${signal['amount_low']:,.0f}-${signal['amount_high']:,.0f}")
                print(f"      Breakdown: {signal['score_breakdown']}")

                if auto_execute:
                    portfolio = open_position(
                        portfolio, signal["ticker"], price, size,
                        signal["score"],
                        f"Pelosi {signal['recommendation']} signal (score {signal['score']})"
                    )
                else:
                    print(f"      👉 ACTION NEEDED: Buy {shares:.2f} shares of {signal['ticker']} "
                          f"at ~${price:.2f} on Robinhood")
    else:
        print("   No new buy signals today.")

    # 6. Process SELL signals
    sell_signals_held = [s for s in actionable if s["action"] == "SELL"
                         and s["ticker"] in portfolio["positions"]]
    sell_signals_watch = [s for s in actionable if s["action"] == "SELL"
                          and s["ticker"] not in portfolio["positions"]]

    if sell_signals_held:
        print("\n   🔔 SELL SIGNALS (positions you hold):")
        for signal in sell_signals_held:
            print(f"      {signal['ticker']} — score {signal['score']}/100")
            if auto_execute and signal.get("price_data"):
                price = signal["price_data"]["current_price"]
                portfolio = close_position(portfolio, signal["ticker"], price,
                                          f"Pelosi sell signal (score {signal['score']})")
            else:
                print(f"      👉 ACTION NEEDED: Sell your {signal['ticker']} position on Robinhood")

    if sell_signals_watch:
        print("\n   📉 BEARISH SIGNALS (Pelosi is selling — avoid or short):")
        for signal in sell_signals_watch[:5]:
            amt = f"${signal['amount_low']:,.0f}-${signal['amount_high']:,.0f}"
            print(f"      {signal['ticker']:<7} score {signal['score']}/100  "
                  f"({amt}, {signal['transaction_date']})")
        print("      ⚠️  Pelosi's sells have historically been the strongest signal.")

    # 7. Portfolio summary
    all_prices = {**held_prices}
    # Add prices for any newly opened positions
    for ticker in portfolio["positions"]:
        if ticker not in all_prices:
            for s in signals:
                if s["ticker"] == ticker and s.get("price_data"):
                    all_prices[ticker] = s["price_data"]
                    break

    summary = get_portfolio_summary(portfolio, all_prices)
    print_portfolio_summary(summary)
    save_performance_snapshot(summary)

    # 8. Strategy optimization check
    print("── STEP 5: Strategy Health Check ──")
    analysis = analyze_past_trades()
    if "message" in analysis:
        print(f"   {analysis['message']}")
    else:
        print(f"   Win Rate: {analysis['win_rate']}%")
        print(f"   Avg Win: ${analysis['avg_win']:.2f} | Avg Loss: ${analysis['avg_loss']:.2f}")
        for suggestion in analysis["suggestions"]:
            print(f"   💡 {suggestion}")

    save_portfolio(portfolio)
    print(f"\n✅ Daily run complete. Next check: tomorrow.\n")

    return summary


if __name__ == "__main__":
    # Run in recommendation mode (manual trading on Robinhood)
    daily_run(auto_execute=False)
