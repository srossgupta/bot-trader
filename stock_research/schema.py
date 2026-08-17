"""
Pick schema, validation, and outcome grading for the nightly stock research
ledger.

Design rules this module enforces (see CLAUDE.md for the routine itself):

  * Verified prices only. A pick without a verified entry price — and a
    verified benchmark price for the same moment — is rejected, not anchored
    to an estimate.
  * Fixed horizon. Every pick declares a horizon in *trading days* and gets a
    `resolve_on` date computed at save time. It is graded once, on that date.
  * Benchmark-relative grading. A pick claims the name beats QQQ by
    WIN_THRESHOLD over the horizon. Raw direction is recorded but does not
    decide the outcome — raw win rate on momentum names in a bull market is
    mostly measuring beta.
  * Confidence is capped at MAX_CONFIDENCE. A 100/100 forecast asserts
    certainty the process cannot support.
"""

from __future__ import annotations

import datetime as dt

from .trading_calendar import add_trading_days, is_trading_day, parse_date

SCHEMA_VERSION = 2

# ── Scoring / grading constants ───────────────────────────────────────────────
MAX_CONFIDENCE = 90            # hard cap; 100/100 is not a forecast, it's a tell
MIN_CONFIDENCE = 60            # below this a pick is not published
DEFAULT_HORIZON_TRADING_DAYS = 3
WIN_THRESHOLD = 0.02           # excess vs benchmark needed to count as a WIN
BENCHMARK_TICKER = "QQQ"

# ── Data quality ──────────────────────────────────────────────────────────────
VERIFIED_PRICE_SOURCES = {"verified_close", "verified_intraday"}

# ── Anti-chasing ──────────────────────────────────────────────────────────────
RUN_UP_LOOKBACK_TRADING_DAYS = 10
CHASE_RUN_UP_THRESHOLD = 0.20  # >20% in 10 sessions = the move already happened
CHASE_PENALTY = -10

# ── Concentration ─────────────────────────────────────────────────────────────
CONCENTRATION_FLAG_THRESHOLD = 0.50  # any bucket at/over this share gets flagged

# ── Rubric-change gating ──────────────────────────────────────────────────────
# Penalties fit on a handful of outcomes are noise dressed up as learning.
MIN_RESOLVED_FOR_RUBRIC_CHANGE = 30

VALID_SIGNALS = {
    "forum_sentiment",
    "fundamental_catalyst",
    "historical_pattern",
    "technical",
    "sector_macro",
    "options",
}

VALID_DIRECTIONS = {"UP", "DOWN"}
VALID_OUTCOMES = {"WIN", "LOSS", "FLAT"}

# Coarse buckets for concentration reporting. Free-text sectors like
# "Semiconductors/AI Infrastructure" and "AI Cloud Infrastructure" are the same
# bet; matched in order, first hit wins.
SECTOR_BUCKETS: list[tuple[str, tuple[str, ...]]] = [
    ("AI/Semis/Tech", (
        "semiconductor", "semis", "ai", "cloud", "software", "saas", "data center",
        "datacenter", "neocloud", "cdn", "edge", "quantum", "cyber", "internet",
        "tech", "hardware", "server", "memory", "chip",
    )),
    ("Aerospace/Defense", ("aerospace", "defense", "space", "drone", "evtol", "satellite")),
    ("Healthcare/Biotech", ("biotech", "pharma", "health", "medical", "glp-1", "device")),
    ("Financials", ("bank", "fintech", "brokerage", "insur", "financ", "payment", "crypto")),
    ("Energy/Materials", ("energy", "oil", "gas", "solar", "uranium", "nuclear",
                          "mining", "materials", "metals", "utilit")),
    ("Consumer/Retail", ("consumer", "retail", "restaurant", "apparel", "auto",
                         "travel", "airline", "media", "entertainment", "e-commerce",
                         "ecommerce")),
    ("Industrials", ("industrial", "transport", "rail", "logistics", "construction",
                     "machinery")),
]


def sector_bucket(sector: str | None) -> str:
    """Map a free-text sector string onto a coarse exposure bucket."""
    text = (sector or "").lower()
    for bucket, keywords in SECTOR_BUCKETS:
        if any(keyword in text for keyword in keywords):
            return bucket
    return "Other"


# ── Validation ────────────────────────────────────────────────────────────────

def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_pick(pick: dict) -> list[str]:
    """Return a list of human-readable problems; empty means the pick is savable."""
    errors: list[str] = []
    ticker = pick.get("ticker") or "<no ticker>"

    def err(msg: str) -> None:
        errors.append(f"{ticker}: {msg}")

    if not pick.get("ticker"):
        errors.append("<no ticker>: 'ticker' is required")
    if not pick.get("company"):
        err("'company' is required")

    if pick.get("direction") not in VALID_DIRECTIONS:
        err(f"'direction' must be one of {sorted(VALID_DIRECTIONS)}, got {pick.get('direction')!r}")

    confidence = pick.get("confidence")
    if not _is_number(confidence):
        err("'confidence' must be a number")
    elif confidence > MAX_CONFIDENCE:
        err(f"confidence {confidence} exceeds the cap of {MAX_CONFIDENCE} — "
            "rescore, do not clamp silently")
    elif confidence < MIN_CONFIDENCE:
        err(f"confidence {confidence} is below the publish floor of {MIN_CONFIDENCE}")

    if not pick.get("sector"):
        err("'sector' is required (used for concentration reporting)")

    signals = pick.get("signals_hit") or []
    if not isinstance(signals, list) or not signals:
        err("'signals_hit' must be a non-empty list")
    else:
        unknown = [s for s in signals if s not in VALID_SIGNALS]
        if unknown:
            err(f"unknown signals {unknown}; valid: {sorted(VALID_SIGNALS)}")

    # Verified prices only — no estimated anchors.
    if not _is_number(pick.get("price_at_pick")) or pick.get("price_at_pick", 0) <= 0:
        err("'price_at_pick' must be a positive number")
    if pick.get("price_source") not in VERIFIED_PRICE_SOURCES:
        err(f"'price_source' must be one of {sorted(VERIFIED_PRICE_SOURCES)} "
            f"(got {pick.get('price_source')!r}) — if no verified price is "
            "available, drop the pick instead of estimating")
    if not pick.get("price_asof"):
        err("'price_asof' (YYYY-MM-DD of the quote) is required")

    if not _is_number(pick.get("benchmark_at_pick")) or pick.get("benchmark_at_pick", 0) <= 0:
        err(f"'benchmark_at_pick' ({pick.get('benchmark_ticker', BENCHMARK_TICKER)} "
            "price on the same date) must be a positive number — grading is "
            "benchmark-relative")

    horizon = pick.get("horizon_trading_days", DEFAULT_HORIZON_TRADING_DAYS)
    if not isinstance(horizon, int) or horizon < 1:
        err("'horizon_trading_days' must be a positive integer")

    run_up = pick.get("run_up_10d_pct")
    if run_up is not None and not _is_number(run_up):
        err("'run_up_10d_pct' must be a number or null")

    return errors


def chase_penalty(pick: dict) -> int:
    """Anti-chasing deduction for a pick that already ran before we noticed it."""
    run_up = pick.get("run_up_10d_pct")
    if _is_number(run_up) and run_up >= CHASE_RUN_UP_THRESHOLD:
        return CHASE_PENALTY
    return 0


def normalize_pick(pick: dict, run_date: str) -> dict:
    """Fill in derived ledger fields. Assumes validate_pick() passed."""
    horizon = int(pick.get("horizon_trading_days", DEFAULT_HORIZON_TRADING_DAYS))
    out = dict(pick)
    out["schema_version"] = SCHEMA_VERSION
    out["benchmark_ticker"] = pick.get("benchmark_ticker", BENCHMARK_TICKER)
    out["horizon_trading_days"] = horizon
    out["resolve_on"] = add_trading_days(run_date, horizon).isoformat()
    out["sector_bucket"] = sector_bucket(pick.get("sector"))
    out["chase_flag"] = chase_penalty(pick) != 0
    out.setdefault("run_up_10d_pct", None)
    out.setdefault("picked_at", None)      # ISO timestamp the email went out
    out.setdefault("next_open_price", None)  # filled in the following session
    out.setdefault("next_open_date", None)
    out.setdefault("slippage_pct", None)
    # Resolution fields — written exactly once, by history.resolve().
    out["resolved"] = False
    out.setdefault("resolution_price", None)
    out.setdefault("resolution_date", None)
    out.setdefault("benchmark_at_resolution", None)
    out.setdefault("pct_change", None)
    out.setdefault("benchmark_pct_change", None)
    out.setdefault("excess_vs_benchmark", None)
    out.setdefault("outcome", None)
    out.setdefault("raw_direction_correct", None)
    out.setdefault("resolved_at", None)
    return out


# ── Grading ───────────────────────────────────────────────────────────────────

def grade(direction: str, entry: float, exit_price: float,
          benchmark_entry: float, benchmark_exit: float,
          threshold: float = WIN_THRESHOLD) -> dict:
    """
    Grade a pick benchmark-relative over its horizon.

    WIN  — excess return beats the benchmark by `threshold`
    LOSS — excess return trails the benchmark by `threshold`
    FLAT — anything in between: the signal did not move the needle

    A DOWN pick wins when the name underperforms, so its excess is negated.
    """
    pct = (exit_price - entry) / entry
    bench_pct = (benchmark_exit - benchmark_entry) / benchmark_entry
    excess = pct - bench_pct
    if direction == "DOWN":
        excess = -excess

    if excess >= threshold:
        outcome = "WIN"
    elif excess <= -threshold:
        outcome = "LOSS"
    else:
        outcome = "FLAT"

    return {
        "pct_change": round(pct, 4),
        "benchmark_pct_change": round(bench_pct, 4),
        "excess_vs_benchmark": round(excess, 4),
        "outcome": outcome,
        "raw_direction_correct": (pct > 0) if direction == "UP" else (pct < 0),
    }


def is_v2(pick: dict) -> bool:
    """True for picks written under the benchmark-relative ledger schema."""
    return pick.get("schema_version", 1) >= 2


def validate_run_date(run_date: str) -> list[str]:
    errors: list[str] = []
    try:
        day = parse_date(run_date)
    except (ValueError, TypeError):
        return [f"run_date {run_date!r} is not a YYYY-MM-DD date"]
    if not is_trading_day(day):
        errors.append(f"run_date {run_date} is not a trading day — the routine "
                      "does not run when the market is closed")
    if day > dt.date.today():
        errors.append(f"run_date {run_date} is in the future")
    return errors
