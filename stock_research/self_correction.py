"""
Self-correction engine for the nightly stock research routine.

Loads the last N runs from history.py, evaluates all picks that have outcomes,
and returns score adjustments to apply to the *current* run's scoring rubric.

Output schema:
  {
    "runs_evaluated": 3,
    "picks_with_outcomes": 7,
    "past_win_rate": 0.57,
    "sector_penalties": {"Semiconductors": -10},   # subtract from raw score
    "signal_penalties": {"technical": -5},          # subtract per signal hit
    "overconfidence_warning": true,                 # cap scores at 80 this run
    "unevaluated_picks": [                          # picks that still need prices
      {"run_date": "2026-05-05", "ticker": "NVDA", "direction": "UP"}
    ],
    "notes": ["...human-readable explanation of each adjustment applied..."]
  }

Thresholds (edit here to tune aggressiveness):
  SECTOR_PENALTY_THRESHOLD  = 0.40  → sector win rate below this gets penalised
  SIGNAL_PENALTY_THRESHOLD  = 0.35  → signal-type win rate below this gets penalised
  MIN_SAMPLES_FOR_PENALTY   = 2     → need at least this many outcomes before penalising
  OVERCONFIDENCE_WIN_FLOOR  = 0.50  → high-confidence (≥80) picks must beat this rate

Usage:
  python -m stock_research.self_correction [N_runs]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict

from .history import load_recent

# ── Tunable thresholds ────────────────────────────────────────────────────────
SECTOR_PENALTY_THRESHOLD = 0.40
SIGNAL_PENALTY_THRESHOLD = 0.35
MIN_SAMPLES_FOR_PENALTY = 2
OVERCONFIDENCE_WIN_FLOOR = 0.50
HIGH_CONFIDENCE_CUTOFF = 80


# ── Main ──────────────────────────────────────────────────────────────────────

def compute_adjustments(n_runs: int = 3) -> dict:
    runs = load_recent(n_runs)

    evaluated: list[dict] = []
    unevaluated: list[dict] = []

    for run in runs:
        date = run.get("run_date", "unknown")
        for pick in run.get("picks", []):
            if pick.get("outcome") in {"WIN", "LOSS"}:
                evaluated.append(pick)
            elif pick.get("price_at_pick"):
                # Has a price but no outcome yet — needs lookup this run
                unevaluated.append({
                    "run_date": date,
                    "ticker": pick["ticker"],
                    "direction": pick.get("direction", "UP"),
                    "price_at_pick": pick["price_at_pick"],
                })

    if not evaluated:
        return {
            "runs_evaluated": len(runs),
            "picks_with_outcomes": 0,
            "past_win_rate": None,
            "sector_penalties": {},
            "signal_penalties": {},
            "overconfidence_warning": False,
            "unevaluated_picks": unevaluated,
            "notes": [
                "No evaluated picks yet — scoring rubric unchanged for this run.",
                *([f"{len(unevaluated)} picks need price lookups before they can be evaluated."]
                  if unevaluated else []),
            ],
        }

    notes: list[str] = []
    wins = sum(1 for p in evaluated if p["outcome"] == "WIN")
    past_win_rate = wins / len(evaluated)

    # ── Per-sector win rate ───────────────────────────────────────────────────
    sector_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "total": 0})
    for pick in evaluated:
        s = pick.get("sector", "Unknown")
        sector_stats[s]["total"] += 1
        if pick["outcome"] == "WIN":
            sector_stats[s]["wins"] += 1

    sector_penalties: dict[str, int] = {}
    for sector, stats in sector_stats.items():
        if stats["total"] < MIN_SAMPLES_FOR_PENALTY:
            continue
        wr = stats["wins"] / stats["total"]
        if wr < SECTOR_PENALTY_THRESHOLD:
            penalty = -10 if wr < 0.25 else -5
            sector_penalties[sector] = penalty
            notes.append(
                f"{sector}: {stats['wins']}/{stats['total']} wins "
                f"({wr:.0%}) → {penalty} pts penalty on sector_macro signal"
            )

    # ── Per-signal win rate ───────────────────────────────────────────────────
    signal_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "total": 0})
    for pick in evaluated:
        for sig in pick.get("signals_hit", []):
            signal_stats[sig]["total"] += 1
            if pick["outcome"] == "WIN":
                signal_stats[sig]["wins"] += 1

    signal_penalties: dict[str, int] = {}
    for sig, stats in signal_stats.items():
        if stats["total"] < MIN_SAMPLES_FOR_PENALTY:
            continue
        wr = stats["wins"] / stats["total"]
        if wr < SIGNAL_PENALTY_THRESHOLD:
            signal_penalties[sig] = -5
            notes.append(
                f"Signal '{sig}': {stats['wins']}/{stats['total']} wins "
                f"({wr:.0%}) → -5 pts deducted when this signal fires"
            )

    # ── Overconfidence check ─────────────────────────────────────────────────
    high_conf = [p for p in evaluated if p.get("confidence", 0) >= HIGH_CONFIDENCE_CUTOFF]
    overconfidence_warning = False
    if len(high_conf) >= MIN_SAMPLES_FOR_PENALTY:
        hc_wr = sum(1 for p in high_conf if p["outcome"] == "WIN") / len(high_conf)
        if hc_wr < OVERCONFIDENCE_WIN_FLOOR:
            overconfidence_warning = True
            notes.append(
                f"Overconfidence: picks scored ≥{HIGH_CONFIDENCE_CUTOFF} "
                f"won only {hc_wr:.0%} — cap all scores at 80 this run"
            )

    if not notes:
        notes.append(
            f"Past win rate {past_win_rate:.0%} across {len(evaluated)} picks "
            f"— no adjustments needed, scoring rubric unchanged."
        )

    return {
        "runs_evaluated": len(runs),
        "picks_with_outcomes": len(evaluated),
        "past_win_rate": round(past_win_rate, 4),
        "sector_penalties": sector_penalties,
        "signal_penalties": signal_penalties,
        "overconfidence_warning": overconfidence_warning,
        "unevaluated_picks": unevaluated,
        "notes": notes,
    }


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    print(json.dumps(compute_adjustments(n), indent=2))
