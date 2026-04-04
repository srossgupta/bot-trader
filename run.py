#!/usr/bin/env python3
"""
Pelosi Algo Trader — Main Runner
==================================
This is the script you run every day.

Usage:
    python run.py              → Daily scan (shows recommendations)
    python run.py --status     → Portfolio status only
    python run.py --signals    → Show latest Pelosi signals only
    python run.py --history    → Show performance history
    python run.py --backtest   → Run a simple backtest on recent signals
    python run.py --reset      → Reset portfolio to starting capital
"""

import argparse
import json
import os
import sys

# Add project dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DATA_DIR, STARTING_CAPITAL, PORTFOLIO_FILE, PERFORMANCE_FILE
from daily_monitor import daily_run
from data_fetcher import get_pelosi_signals, fetch_prices_for_tickers, fetch_historical_prices
from signal_scorer import rank_signals
from portfolio_manager import (
    load_portfolio,
    save_portfolio,
    get_portfolio_summary,
    print_portfolio_summary,
)


def cmd_daily():
    """Run the full daily scan."""
    daily_run(auto_execute=False)


def cmd_status():
    """Show current portfolio status."""
    portfolio = load_portfolio()
    held_tickers = list(portfolio["positions"].keys())

    if held_tickers:
        from data_fetcher import fetch_prices_for_tickers
        prices = fetch_prices_for_tickers(held_tickers)
    else:
        prices = {}

    summary = get_portfolio_summary(portfolio, prices)
    print_portfolio_summary(summary)


def cmd_signals():
    """Show latest Pelosi signals without taking action."""
    signals = get_pelosi_signals()
    ranked = rank_signals(signals)

    # Suppress conflicting buys: if Pelosi has a higher-scoring sell for
    # the same ticker, the buy is noise — mark it as CONFLICTED
    sell_scores = {}
    for s in ranked:
        if s["action"] == "SELL":
            sell_scores[s["ticker"]] = max(sell_scores.get(s["ticker"], 0), s["score"])

    for s in ranked:
        if s["action"] == "BUY" and s["ticker"] in sell_scores:
            if sell_scores[s["ticker"]] > s["score"]:
                s["recommendation"] = "CONFLICTED"

    print(f"\n{'='*74}")
    print(f"  📊 LATEST PELOSI TRADE SIGNALS (Top 15)")
    print(f"{'='*74}")
    print(f"  {'#':<4} {'Action':<6} {'Ticker':<8} {'Score':<7} {'Rec':<14} {'Amount':<18} {'Date'}")
    print(f"  {'-'*72}")

    for i, s in enumerate(ranked[:15], 1):
        amt = f"${s['amount_low']:,.0f}-${s['amount_high']:,.0f}"
        flag = " ⚠️" if s["recommendation"] == "CONFLICTED" else ""
        print(f"  {i:<4} {s['action']:<6} {s['ticker']:<8} {s['score']:<7.0f} "
              f"{s['recommendation']:<14} {amt:<18} {s['transaction_date']}{flag}")

    conflicted = [s for s in ranked if s["recommendation"] == "CONFLICTED"]
    if conflicted:
        tickers = ", ".join(sorted(set(s["ticker"] for s in conflicted)))
        print(f"\n  ⚠️  {tickers}: Pelosi bought AND sold — sell signal is stronger, buy suppressed")

    print(f"{'='*74}\n")


def cmd_history():
    """Show performance history."""
    if not os.path.exists(PERFORMANCE_FILE):
        print("No performance history yet. Run a daily scan first.")
        return

    with open(PERFORMANCE_FILE) as f:
        history = json.load(f)

    print(f"\n{'='*60}")
    print(f"  📈 PERFORMANCE HISTORY")
    print(f"{'='*60}")
    print(f"  {'Date':<12} {'Value':>10} {'Return':>10} {'Cash':>10} {'Positions':>5}")
    print(f"  {'-'*50}")

    for h in history:
        emoji = "🟢" if h["total_return_pct"] >= 0 else "🔴"
        print(f"  {h['date']:<12} ${h['total_value']:>9,.2f} {emoji}{h['total_return_pct']:>+8.1f}% "
              f"${h['cash']:>9,.2f} {h['num_positions']:>5}")

    print(f"{'='*60}\n")


def cmd_backtest():
    """Backtest: show actual returns if you followed Pelosi's trades."""
    import time

    print("\n📐 Running backtest on recent Pelosi signals...\n")
    signals = get_pelosi_signals()
    ranked = rank_signals(signals)

    # Deduplicate by (ticker, date, action) to avoid showing the same trade twice
    seen = set()
    unique_signals = []
    for s in ranked:
        key = (s["ticker"], s["transaction_date"], s["action"])
        if key not in seen:
            seen.add(key)
            unique_signals.append(s)

    if not unique_signals:
        print("No signals to backtest.")
        return

    # Fetch historical prices from each trade date
    print(f"📈 Fetching historical prices for {len(unique_signals)} signals...\n")
    results = []
    for s in unique_signals:
        hist = fetch_historical_prices(s["ticker"], s["transaction_date"])
        if not hist or len(hist["daily"]) < 2:
            continue

        daily = hist["daily"]
        entry_price = daily[0]["close"]

        def return_at(n):
            """Get return after n trading days, or None if not enough data."""
            if len(daily) > n and entry_price:
                return (daily[n]["close"] - entry_price) / entry_price
            return None

        # For sells, invert the return (profit if price dropped after Pelosi sold)
        multiplier = -1 if s["action"] == "SELL" else 1

        r5 = return_at(5)
        r20 = return_at(20)
        r_now = return_at(len(daily) - 1)
        days_held = len(daily) - 1

        results.append({
            **s,
            "entry_price": entry_price,
            "r5": r5 * multiplier if r5 is not None else None,
            "r20": r20 * multiplier if r20 is not None else None,
            "r_now": r_now * multiplier if r_now is not None else None,
            "days_held": days_held,
            "current_price": daily[-1]["close"],
        })
        time.sleep(0.3)

    if not results:
        print("No signals with historical price data to backtest.")
        return

    # ── BUY signals ──
    buys = [r for r in results if r["action"] == "BUY"]
    sells = [r for r in results if r["action"] == "SELL"]

    for label, group in [("BUY SIGNALS (follow her purchases)", buys),
                         ("SELL SIGNALS (follow her sales)", sells)]:
        if not group:
            continue

        print(f"  {'─'*74}")
        print(f"  {label}")
        print(f"  {'─'*74}")
        print(f"  {'Ticker':<7} {'Date':<12} {'Entry':>8} {'Now':>8} "
              f"{'5d':>8} {'20d':>8} {'Total':>8} {'Days':>5}")
        print(f"  {'─'*74}")

        sum_5, sum_20, sum_total = [], [], []
        wins_5, wins_20, wins_total = 0, 0, 0

        for r in group:
            r5_str = f"{r['r5']*100:+.1f}%" if r['r5'] is not None else "  N/A"
            r20_str = f"{r['r20']*100:+.1f}%" if r['r20'] is not None else "  N/A"
            now_str = f"{r['r_now']*100:+.1f}%" if r['r_now'] is not None else "  N/A"

            if r['r5'] is not None:
                sum_5.append(r['r5'])
                if r['r5'] > 0: wins_5 += 1
            if r['r20'] is not None:
                sum_20.append(r['r20'])
                if r['r20'] > 0: wins_20 += 1
            if r['r_now'] is not None:
                sum_total.append(r['r_now'])
                if r['r_now'] > 0: wins_total += 1

            emoji = "🟢" if (r['r_now'] or 0) >= 0 else "🔴"
            print(f"  {r['ticker']:<7} {r['transaction_date']:<12} "
                  f"${r['entry_price']:>7.2f} ${r['current_price']:>7.2f} "
                  f"{r5_str:>8} {r20_str:>8} {now_str:>7}{emoji} {r['days_held']:>4}d")

        # Summary stats
        print(f"  {'─'*74}")
        n = len(group)
        avg5 = sum(sum_5)/len(sum_5)*100 if sum_5 else 0
        avg20 = sum(sum_20)/len(sum_20)*100 if sum_20 else 0
        avg_tot = sum(sum_total)/len(sum_total)*100 if sum_total else 0
        print(f"  Avg return     ({n} trades)"
              f"{'':>20} {avg5:>+7.1f}% {avg20:>+7.1f}% {avg_tot:>+7.1f}%")
        if sum_5:
            print(f"  Win rate (5d):  {wins_5}/{len(sum_5)} ({wins_5/len(sum_5)*100:.0f}%)    "
                  f"Win rate (20d): {wins_20}/{len(sum_20)} ({wins_20/len(sum_20)*100:.0f}%)    "
                  f"Win rate (total): {wins_total}/{len(sum_total)} ({wins_total/len(sum_total)*100:.0f}%)")
        print()

    # ── Benchmark comparison (SPY) ──
    if results:
        earliest_date = min(r["transaction_date"] for r in results)
        spy = fetch_historical_prices("SPY", earliest_date)
        if spy and len(spy["daily"]) >= 2:
            spy_entry = spy["daily"][0]["close"]
            spy_now = spy["daily"][-1]["close"]
            spy_ret = (spy_now - spy_entry) / spy_entry * 100
            spy_days = len(spy["daily"]) - 1
            print(f"  {'─'*74}")
            print(f"  📊 BENCHMARK: SPY {spy_ret:+.1f}% over same period "
                  f"(${spy_entry:.2f} → ${spy_now:.2f}, {spy_days}d)")
            print(f"  {'─'*74}")
        print()


def cmd_reset():
    """Reset portfolio to starting capital."""
    confirm = input(f"⚠️  Reset portfolio to ${STARTING_CAPITAL}? All positions will be cleared. (y/N): ")
    if confirm.lower() == "y":
        portfolio = {
            "cash": STARTING_CAPITAL,
            "starting_capital": STARTING_CAPITAL,
            "positions": {},
            "created_at": __import__("datetime").datetime.now().isoformat(),
            "updated_at": __import__("datetime").datetime.now().isoformat(),
        }
        save_portfolio(portfolio)
        print(f"✅ Portfolio reset to ${STARTING_CAPITAL:.2f}")
    else:
        print("Cancelled.")


def main():
    parser = argparse.ArgumentParser(
        description="Pelosi Algo Trader — Congressional trade-following strategy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py              Run daily scan (recommendations)
  python run.py --status     Show portfolio status
  python run.py --signals    Show latest Pelosi signals
  python run.py --history    Show performance over time
  python run.py --backtest   Quick backtest on recent signals
  python run.py --reset      Reset portfolio to $500
        """
    )
    parser.add_argument("--status", action="store_true", help="Show portfolio status")
    parser.add_argument("--signals", action="store_true", help="Show latest signals")
    parser.add_argument("--history", action="store_true", help="Show performance history")
    parser.add_argument("--backtest", action="store_true", help="Run simple backtest")
    parser.add_argument("--reset", action="store_true", help="Reset portfolio")

    args = parser.parse_args()

    if args.status:
        cmd_status()
    elif args.signals:
        cmd_signals()
    elif args.history:
        cmd_history()
    elif args.backtest:
        cmd_backtest()
    elif args.reset:
        cmd_reset()
    else:
        cmd_daily()


if __name__ == "__main__":
    main()
