"""
Pelosi Algo Trader — Signal Scoring Engine
============================================
Scores each Pelosi trade signal from 0-100 based on multiple factors.
Higher score = stronger conviction = bigger position.

Scoring Factors:
1. Trade freshness (how recently was it disclosed?)
2. Trade size (bigger Pelosi trades = more conviction)
3. Momentum alignment (is the stock trending in the right direction?)
4. Volume confirmation (is there unusual volume?)
5. Sector boost (Pelosi's tech trades historically do well)
6. Proximity to 52-week levels
7. Repeat signal (has Pelosi traded this before recently?)
"""

from datetime import datetime, timedelta
from config import (
    FRESHNESS_WINDOW_DAYS,
    SECTOR_BOOST,
    MIN_SIGNAL_SCORE,
    STRONG_SIGNAL_SCORE,
)


# ── INDIVIDUAL SCORING COMPONENTS ──────────────────────────────────

def score_freshness(signal: dict) -> float:
    """
    Score 0-20 based on how recently the trade was disclosed.
    Fresher = better (we want to act before the crowd).
    """
    disclosure_str = signal.get("disclosure_date", "")
    if not disclosure_str:
        return 5  # Unknown date gets a middling score

    try:
        disclosure_date = datetime.strptime(disclosure_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return 5

    days_ago = (datetime.now() - disclosure_date).days

    if days_ago <= 1:
        return 20    # Just disclosed today/yesterday — maximum edge
    elif days_ago <= 3:
        return 17
    elif days_ago <= 7:
        return 14
    elif days_ago <= 14:
        return 10
    elif days_ago <= 30:
        return 6
    else:
        return 2     # Stale disclosure


def score_trade_size(signal: dict) -> float:
    """
    Score 0-25 based on the size of Pelosi's trade.
    Bigger trades = more conviction from her side.
    Sell signals get a bonus — large sells are historically the strongest signal.
    """
    amount_high = signal.get("amount_high", 0)
    action = signal.get("action", "BUY")

    if amount_high >= 5_000_000:
        base = 20    # $5M+ = massive conviction
    elif amount_high >= 1_000_000:
        base = 17
    elif amount_high >= 500_000:
        base = 14
    elif amount_high >= 250_000:
        base = 11
    elif amount_high >= 100_000:
        base = 8
    elif amount_high >= 50_000:
        base = 5
    else:
        base = 2     # Small trade, less informative

    # Large sells are the strongest Pelosi signal historically
    if action == "SELL" and amount_high >= 1_000_000:
        base += 5

    return min(25, base)


def score_momentum(signal: dict) -> float:
    """
    Score 0-20 based on price momentum alignment.
    For BUY signals: we want upward momentum (but not overbought).
    For SELL signals: we want to confirm downward pressure.
    """
    price_data = signal.get("price_data")
    if not price_data:
        return 10  # No data, neutral score

    action = signal.get("action", "BUY")
    five_day = price_data.get("five_day_return")
    twenty_day = price_data.get("twenty_day_return")

    score = 10  # Start neutral

    if action == "BUY":
        # Ideal: slight positive momentum (not overextended)
        if five_day is not None:
            if 0.0 <= five_day <= 0.03:
                score += 5   # Gentle uptrend — ideal entry
            elif 0.03 < five_day <= 0.08:
                score += 3   # Good momentum
            elif -0.03 <= five_day < 0:
                score += 2   # Small dip — possible buy-the-dip
            elif five_day > 0.10:
                score -= 3   # Overextended — risky entry
            elif five_day < -0.05:
                score -= 2   # Falling hard — wait

        if twenty_day is not None:
            if twenty_day > 0.05:
                score += 3   # Strong monthly trend
            elif twenty_day > 0:
                score += 1
            elif twenty_day < -0.10:
                score -= 3   # Monthly downtrend

    elif action == "SELL":
        # Pelosi's sells are the strongest signal — she exits before drops
        if five_day is not None:
            if five_day > 0.03:
                score += 5   # Still going up — she's selling into strength (bearish)
            elif five_day > 0:
                score += 3   # Flat/slight up — smart exit
            elif five_day < -0.03:
                score += 4   # Already dropping — confirms her call

        if twenty_day is not None:
            if twenty_day > 0.05:
                score += 3   # Selling after a run-up — taking profits
            elif twenty_day < -0.05:
                score += 2   # Selling into weakness — cutting losses

    return max(0, min(25, score))


def score_volume(signal: dict) -> float:
    """
    Score 0-15 based on volume confirmation.
    Unusual volume = smart money is moving.
    """
    price_data = signal.get("price_data")
    if not price_data:
        return 7

    latest_vol = price_data.get("latest_volume", 0)
    avg_vol = price_data.get("avg_volume", 1)

    if avg_vol == 0:
        return 7

    vol_ratio = latest_vol / avg_vol

    if vol_ratio >= 2.0:
        return 15    # 2x+ average volume — big institutional activity
    elif vol_ratio >= 1.5:
        return 12
    elif vol_ratio >= 1.0:
        return 9
    elif vol_ratio >= 0.7:
        return 6
    else:
        return 3     # Low volume — no confirmation


def score_52week_position(signal: dict) -> float:
    """
    Score 0-10 based on where the price is relative to 52-week range.
    For BUY: prefer stocks not at 52-week highs (room to run).
    For SELL: confirm they're near highs.
    """
    price_data = signal.get("price_data")
    if not price_data:
        return 5

    current = price_data.get("current_price", 0)
    high_52 = price_data.get("fifty_two_week_high")
    low_52 = price_data.get("fifty_two_week_low")

    if not high_52 or not low_52 or high_52 == low_52:
        return 5

    # Where in the 52-week range is the price? (0 = at low, 1 = at high)
    position = (current - low_52) / (high_52 - low_52)

    action = signal.get("action", "BUY")

    if action == "BUY":
        if 0.3 <= position <= 0.7:
            return 10    # Mid-range — best risk/reward
        elif 0.2 <= position <= 0.8:
            return 7
        elif position < 0.2:
            return 4     # Near 52-week low — could be value trap
        else:
            return 3     # Near 52-week high — limited upside
    elif action == "SELL":
        if position > 0.7:
            return 10    # Near highs — she's selling the top
        elif position > 0.4:
            return 8     # Mid-range sell — still informative
        else:
            return 5     # Near lows — less useful as signal

    return 5


def score_sector(signal: dict) -> float:
    """
    Score multiplier based on sector. Pelosi's tech picks historically
    outperform, so we give a small boost to her wheelhouse.
    Returns a multiplier (0.95 to 1.15).
    """
    # We'd ideally look up the sector from the ticker, but for simplicity
    # we'll use the asset description to guess
    desc = signal.get("asset_description", "").lower()

    # Simple keyword-based sector detection
    tech_keywords = ["apple", "nvidia", "google", "alphabet", "microsoft", "amazon",
                     "meta", "crowdstrike", "salesforce", "adobe", "tesla", "semiconductor",
                     "software", "cloud", "ai ", "artificial"]
    health_keywords = ["health", "pharma", "bio", "medical", "therapeutics"]
    finance_keywords = ["bank", "financial", "capital", "jpmorgan", "goldman"]
    energy_keywords = ["energy", "oil", "gas", "solar", "wind"]

    if any(kw in desc for kw in tech_keywords):
        return SECTOR_BOOST.get("Technology", 1.0)
    elif any(kw in desc for kw in health_keywords):
        return SECTOR_BOOST.get("Healthcare", 1.0)
    elif any(kw in desc for kw in finance_keywords):
        return SECTOR_BOOST.get("Financials", 1.0)
    elif any(kw in desc for kw in energy_keywords):
        return SECTOR_BOOST.get("Energy", 1.0)
    else:
        return SECTOR_BOOST.get("Other", 1.0)


def score_repeat_signal(signal: dict, all_signals: list[dict]) -> float:
    """
    Score 0-15: bonus if Pelosi has traded this ticker multiple times recently.
    Repeated buys = strong conviction.
    """
    ticker = signal.get("ticker")
    action = signal.get("action")
    count = 0

    for s in all_signals:
        if s.get("ticker") == ticker and s.get("action") == action:
            count += 1

    if count >= 3:
        return 15    # 3+ trades in same direction = very strong
    elif count == 2:
        return 10
    else:
        return 3     # Single trade


# ── MAIN SCORING FUNCTION ─────────────────────────────────────────

def score_signal(signal: dict, all_signals: list[dict] = None) -> dict:
    """
    Score a Pelosi trade signal on a 0-100 scale.

    Returns the signal dict enriched with:
      - score: overall score (0-100)
      - score_breakdown: dict of individual component scores
      - recommendation: "STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL", "SKIP"
    """
    if all_signals is None:
        all_signals = []

    # Calculate component scores
    freshness = score_freshness(signal)
    trade_size = score_trade_size(signal)
    momentum = score_momentum(signal)
    volume = score_volume(signal)
    week52 = score_52week_position(signal)
    repeat = score_repeat_signal(signal, all_signals)
    sector_mult = score_sector(signal)

    # Raw score (sum of components, max ~115 for sells, ~100 for buys)
    raw_score = freshness + trade_size + momentum + volume + week52 + repeat
    # Apply sector multiplier and normalize to 0-100
    final_score = min(100, raw_score * sector_mult)

    # Determine recommendation — sell signals use a lower threshold
    # since backtest shows Pelosi's sells are the strongest alpha
    action = signal.get("action", "BUY")
    sell_threshold = max(40, MIN_SIGNAL_SCORE - 15)

    if action == "BUY":
        if final_score >= STRONG_SIGNAL_SCORE:
            recommendation = "STRONG_BUY"
        elif final_score >= MIN_SIGNAL_SCORE:
            recommendation = "BUY"
        else:
            recommendation = "SKIP"
    elif action == "SELL":
        if final_score >= STRONG_SIGNAL_SCORE:
            recommendation = "STRONG_SELL"
        elif final_score >= sell_threshold:
            recommendation = "SELL"
        else:
            recommendation = "SKIP"
    else:
        recommendation = "SKIP"

    signal["score"] = round(final_score, 1)
    signal["score_breakdown"] = {
        "freshness": freshness,
        "trade_size": trade_size,
        "momentum": momentum,
        "volume": volume,
        "52_week_position": week52,
        "repeat_signal": repeat,
        "sector_multiplier": sector_mult,
    }
    signal["recommendation"] = recommendation

    return signal


def rank_signals(signals: list[dict]) -> list[dict]:
    """
    Score all signals and return them ranked by score (highest first).
    """
    scored = [score_signal(s, signals) for s in signals]
    scored.sort(key=lambda s: s["score"], reverse=True)
    return scored


def get_actionable_signals(signals: list[dict]) -> list[dict]:
    """
    Return only signals that meet the minimum score threshold.
    """
    ranked = rank_signals(signals)
    return [s for s in ranked if s["score"] >= MIN_SIGNAL_SCORE]


if __name__ == "__main__":
    # Test with sample data
    sample = {
        "ticker": "NVDA",
        "action": "BUY",
        "amount_low": 1_000_000,
        "amount_high": 5_000_000,
        "transaction_date": "2024-01-15",
        "disclosure_date": "2024-01-20",
        "asset_description": "NVIDIA Corporation",
        "price_data": {
            "current_price": 600,
            "prev_close": 595,
            "day_change_pct": 0.84,
            "five_day_return": 0.02,
            "twenty_day_return": 0.08,
            "avg_volume": 50_000_000,
            "latest_volume": 75_000_000,
            "fifty_two_week_high": 650,
            "fifty_two_week_low": 400,
        },
    }
    result = score_signal(sample)
    print(f"\n{'='*50}")
    print(f"  {result['ticker']} — Score: {result['score']}/100")
    print(f"  Recommendation: {result['recommendation']}")
    print(f"  Breakdown: {result['score_breakdown']}")
