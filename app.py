"""
Pelosi Algo Trader — Web Dashboard
====================================
Flask app that surfaces signals, backtest, and portfolio data.

Usage:
    python app.py
    → opens http://localhost:5050
"""

import time
from datetime import datetime
from flask import Flask, render_template, jsonify

from config import MIN_SIGNAL_SCORE, STARTING_CAPITAL
from data_fetcher import get_pelosi_signals, fetch_historical_prices
from signal_scorer import rank_signals
from portfolio_manager import load_portfolio, get_portfolio_summary
from data_fetcher import fetch_prices_for_tickers
from daily_monitor import detect_new_trades, load_performance_history

app = Flask(__name__)

# ── Cache to avoid hammering APIs on every page load ──────────────
_cache = {"signals": None, "ranked": None, "ts": 0}
CACHE_TTL = 300  # 5 minutes


def _get_signals():
    """Fetch and score signals, with caching."""
    now = time.time()
    if _cache["signals"] and (now - _cache["ts"]) < CACHE_TTL:
        return _cache["signals"], _cache["ranked"]

    signals = get_pelosi_signals()
    ranked = rank_signals(signals)

    # Mark conflicted buys
    sell_scores = {}
    for s in ranked:
        if s["action"] == "SELL":
            sell_scores[s["ticker"]] = max(sell_scores.get(s["ticker"], 0), s["score"])
    for s in ranked:
        if s["action"] == "BUY" and s["ticker"] in sell_scores:
            if sell_scores[s["ticker"]] > s["score"]:
                s["conflicted"] = True

    _cache["signals"] = signals
    _cache["ranked"] = ranked
    _cache["ts"] = now
    return signals, ranked


@app.route("/")
def dashboard():
    signals, ranked = _get_signals()
    new_trades = detect_new_trades(signals)

    # Portfolio
    portfolio = load_portfolio()
    held_tickers = list(portfolio["positions"].keys())
    prices = fetch_prices_for_tickers(held_tickers) if held_tickers else {}
    summary = get_portfolio_summary(portfolio, prices)

    # Performance history
    history = load_performance_history()

    return render_template(
        "dashboard.html",
        ranked=ranked,
        new_trades=new_trades,
        summary=summary,
        history=history,
        min_score=MIN_SIGNAL_SCORE,
        now=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


@app.route("/api/backtest")
def api_backtest():
    """Run backtest and return JSON results."""
    signals, ranked = _get_signals()

    # Deduplicate
    seen = set()
    unique = []
    for s in ranked:
        key = (s["ticker"], s["transaction_date"], s["action"])
        if key not in seen:
            seen.add(key)
            unique.append(s)

    results = []
    for s in unique:
        hist = fetch_historical_prices(s["ticker"], s["transaction_date"])
        if not hist or len(hist["daily"]) < 2:
            continue

        daily = hist["daily"]
        entry = daily[0]["close"]
        multiplier = -1 if s["action"] == "SELL" else 1

        def ret_at(n):
            if len(daily) > n and entry:
                return round((daily[n]["close"] - entry) / entry * multiplier, 4)
            return None

        results.append({
            "ticker": s["ticker"],
            "action": s["action"],
            "date": s["transaction_date"],
            "entry_price": round(entry, 2),
            "current_price": round(daily[-1]["close"], 2),
            "r5": ret_at(5),
            "r20": ret_at(20),
            "r_total": ret_at(len(daily) - 1),
            "days": len(daily) - 1,
            "score": s["score"],
        })
        time.sleep(0.3)

    # SPY benchmark
    spy_data = None
    if results:
        earliest = min(r["date"] for r in results)
        spy = fetch_historical_prices("SPY", earliest)
        if spy and len(spy["daily"]) >= 2:
            spy_data = {
                "entry": round(spy["daily"][0]["close"], 2),
                "current": round(spy["daily"][-1]["close"], 2),
                "return": round((spy["daily"][-1]["close"] - spy["daily"][0]["close"]) / spy["daily"][0]["close"], 4),
                "days": len(spy["daily"]) - 1,
            }

    return jsonify({"results": results, "spy": spy_data})


if __name__ == "__main__":
    print("\n  Pelosi Algo Trader Dashboard")
    print("  http://localhost:5050\n")
    app.run(debug=True, port=5050)
