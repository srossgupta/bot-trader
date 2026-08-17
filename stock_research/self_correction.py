"""
Self-correction and calibration report for the nightly stock research routine.

What changed from the original version, and why:

  * Outcomes are benchmark-relative. Raw win rate on a book of AI/semi momentum
    names in a bull market mostly measures beta, so it is reported only as
    context and never drives an adjustment.
  * Rubric changes are gated on sample size. Fitting sector and signal
    penalties to a handful of outcomes is noise dressed up as learning; below
    MIN_RESOLVED_FOR_RUBRIC_CHANGE resolved picks the rubric is left alone.
  * Confidence is scored, not just tallied. Brier score plus a reliability
    table answer "is an 85 actually an 85?", which raw win rate cannot.
  * Concentration and slippage are reported every run: what the book is
    actually exposed to, and how much of the signal is gone by the next open.

Usage:
  python -m stock_research.self_correction [N_runs_for_window]
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict

from . import schema
from .history import due_for_resolution, load_all_runs, load_recent

# ── Tunable thresholds ────────────────────────────────────────────────────────
SECTOR_PENALTY_THRESHOLD = 0.40   # bucket win rate below this gets penalised
SIGNAL_PENALTY_THRESHOLD = 0.35   # signal win rate below this gets penalised
MIN_SAMPLES_PER_CATEGORY = 10     # per-sector / per-signal minimum before penalising
CALIBRATION_BUCKETS = [(60, 69), (70, 79), (80, 90)]


def _resolved_picks(runs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split resolved picks into benchmark-relative (v2) and legacy (v1)."""
    v2, legacy = [], []
    for run in runs:
        for pick in run.get("picks", []):
            if not (pick.get("resolved") or pick.get("outcome")):
                continue
            (v2 if schema.is_v2(pick) else legacy).append(pick)
    return v2, legacy


def _win_rate(picks: list[dict]) -> float | None:
    if not picks:
        return None
    return sum(1 for p in picks if p.get("outcome") == "WIN") / len(picks)


def _calibration(picks: list[dict]) -> dict:
    """
    Brier score over the forecast "this pick beats the benchmark by 2%".

    Confidence/100 is read as that probability. Skill is measured against the
    no-skill baseline of always forecasting the observed base rate.
    """
    scored = [p for p in picks if isinstance(p.get("confidence"), (int, float))]
    if not scored:
        return {"picks_scored": 0, "brier": None, "baseline_brier": None,
                "skill_vs_base_rate": None, "mean_confidence": None,
                "realized_win_rate": None, "reliability": []}

    outcomes = [1.0 if p.get("outcome") == "WIN" else 0.0 for p in scored]
    forecasts = [min(p["confidence"], schema.MAX_CONFIDENCE) / 100 for p in scored]
    base_rate = sum(outcomes) / len(outcomes)

    brier = sum((f - o) ** 2 for f, o in zip(forecasts, outcomes)) / len(scored)
    baseline = sum((base_rate - o) ** 2 for o in outcomes) / len(scored)
    skill = None if baseline == 0 else round(1 - brier / baseline, 4)

    reliability = []
    for low, high in CALIBRATION_BUCKETS:
        bucket = [(f, o) for p, f, o in zip(scored, forecasts, outcomes)
                  if low <= p["confidence"] <= high]
        if not bucket:
            continue
        reliability.append({
            "confidence_band": f"{low}-{high}",
            "n": len(bucket),
            "mean_forecast": round(sum(f for f, _ in bucket) / len(bucket), 3),
            "observed_win_rate": round(sum(o for _, o in bucket) / len(bucket), 3),
        })

    return {
        "picks_scored": len(scored),
        "brier": round(brier, 4),
        "baseline_brier": round(baseline, 4),
        "skill_vs_base_rate": skill,
        "mean_confidence": round(sum(forecasts) / len(forecasts), 3),
        "realized_win_rate": round(base_rate, 3),
        "reliability": reliability,
    }


def _concentration(runs: list[dict]) -> dict:
    """Sector-bucket exposure across the window, including unresolved picks."""
    counts: dict[str, int] = defaultdict(int)
    total = 0
    for run in runs:
        for pick in run.get("picks", []):
            bucket = pick.get("sector_bucket") or schema.sector_bucket(pick.get("sector"))
            counts[bucket] += 1
            total += 1
    if not total:
        return {"picks": 0, "by_bucket": {}, "top_bucket": None, "top_share": None,
                "flag": False}

    shares = {b: round(c / total, 3) for b, c in sorted(counts.items(), key=lambda kv: -kv[1])}
    top_bucket, top_share = next(iter(shares.items()))
    return {
        "picks": total,
        "by_bucket": {b: {"picks": counts[b], "share": shares[b]} for b in shares},
        "top_bucket": top_bucket,
        "top_share": top_share,
        "flag": top_share >= schema.CONCENTRATION_FLAG_THRESHOLD,
    }


def _slippage(picks: list[dict]) -> dict:
    """How much of the move is gone by the next open — the cost of chasing."""
    measured = [p["slippage_pct"] for p in picks
                if isinstance(p.get("slippage_pct"), (int, float))]
    chased = [p for p in picks if p.get("chase_flag")]
    run_ups = [p["run_up_10d_pct"] for p in picks
               if isinstance(p.get("run_up_10d_pct"), (int, float))]
    return {
        "picks_with_next_open": len(measured),
        "mean_slippage_pct": round(statistics.fmean(measured), 4) if measured else None,
        "median_slippage_pct": round(statistics.median(measured), 4) if measured else None,
        "picks_with_run_up_measured": len(run_ups),
        "mean_run_up_10d_pct": round(statistics.fmean(run_ups), 4) if run_ups else None,
        "chase_flagged_picks": len(chased),
    }


def _category_penalties(picks: list[dict], notes: list[str]) -> tuple[dict, dict]:
    """Per-bucket and per-signal penalties. Only called once the sample supports it."""
    sector_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "total": 0})
    signal_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "total": 0})

    for pick in picks:
        won = pick.get("outcome") == "WIN"
        bucket = pick.get("sector_bucket") or schema.sector_bucket(pick.get("sector"))
        sector_stats[bucket]["total"] += 1
        sector_stats[bucket]["wins"] += int(won)
        for sig in pick.get("signals_hit", []):
            signal_stats[sig]["total"] += 1
            signal_stats[sig]["wins"] += int(won)

    sector_penalties: dict[str, int] = {}
    for bucket, stats in sector_stats.items():
        if stats["total"] < MIN_SAMPLES_PER_CATEGORY:
            continue
        wr = stats["wins"] / stats["total"]
        if wr < SECTOR_PENALTY_THRESHOLD:
            penalty = -10 if wr < 0.25 else -5
            sector_penalties[bucket] = penalty
            notes.append(f"{bucket}: {stats['wins']}/{stats['total']} benchmark-relative wins "
                         f"({wr:.0%}) → {penalty} pts when sector_macro fires for it")

    signal_penalties: dict[str, int] = {}
    for sig, stats in signal_stats.items():
        if stats["total"] < MIN_SAMPLES_PER_CATEGORY:
            continue
        wr = stats["wins"] / stats["total"]
        if wr < SIGNAL_PENALTY_THRESHOLD:
            signal_penalties[sig] = -5
            notes.append(f"Signal '{sig}': {stats['wins']}/{stats['total']} wins "
                         f"({wr:.0%}) → -5 pts when it fires")

    return sector_penalties, signal_penalties


def compute_adjustments(n_runs: int = 3) -> dict:
    """
    Calibration report plus any rubric adjustments earned by the sample.

    Calibration and penalties use the full ledger — a 3-run window is far too
    small to fit anything to. The window only frames "what have we been doing
    lately" for concentration and slippage.
    """
    all_runs = load_all_runs()
    window = load_recent(n_runs)

    resolved, legacy = _resolved_picks(all_runs)
    notes: list[str] = []

    sample_ok = len(resolved) >= schema.MIN_RESOLVED_FOR_RUBRIC_CHANGE
    sector_penalties: dict[str, int] = {}
    signal_penalties: dict[str, int] = {}

    if sample_ok:
        sector_penalties, signal_penalties = _category_penalties(resolved, notes)
        if not sector_penalties and not signal_penalties:
            notes.append(f"{len(resolved)} benchmark-relative outcomes — no category "
                         "underperformed enough to earn a penalty; rubric unchanged.")
    else:
        notes.append(
            f"Sample too small for rubric changes: {len(resolved)} benchmark-relative "
            f"outcomes vs {schema.MIN_RESOLVED_FOR_RUBRIC_CHANGE} required. "
            "No sector or signal penalties applied this run."
        )

    if legacy:
        legacy_wr = _win_rate(legacy)
        notes.append(
            f"{len(legacy)} legacy picks graded raw-direction (win rate {legacy_wr:.0%}) "
            "are excluded from calibration — raw direction in a bull market is beta, "
            "not skill."
        )

    calibration = _calibration(resolved)
    concentration = _concentration(window)
    slippage = _slippage([p for run in all_runs for p in run.get("picks", [])])

    if concentration["flag"]:
        notes.append(
            f"CONCENTRATION: {concentration['top_share']:.0%} of the last {n_runs} runs' "
            f"picks are {concentration['top_bucket']}. One sector drawdown flips the "
            "whole record — diversify or state the exposure explicitly in the email."
        )

    if slippage["mean_slippage_pct"] is not None and slippage["mean_slippage_pct"] > 0.01:
        notes.append(
            f"CHASING: mean next-open slippage is {slippage['mean_slippage_pct']:.2%} — "
            "that much of the signal is gone before the position could be entered."
        )

    # Overconfidence is now a calibration question, not a win-rate question.
    overconfidence_warning = False
    if calibration["picks_scored"] >= schema.MIN_RESOLVED_FOR_RUBRIC_CHANGE:
        gap = calibration["mean_confidence"] - calibration["realized_win_rate"]
        if gap > 0.15:
            overconfidence_warning = True
            notes.append(
                f"Overconfident: mean forecast {calibration['mean_confidence']:.0%} vs "
                f"realized {calibration['realized_win_rate']:.0%} "
                f"(gap {gap:.0%}) — shade every score down."
            )

    return {
        "window_runs": len(window),
        "total_runs": len(all_runs),
        "grading": {
            "basis": f"excess return vs {schema.BENCHMARK_TICKER}",
            "horizon_trading_days": schema.DEFAULT_HORIZON_TRADING_DAYS,
            "win_threshold": schema.WIN_THRESHOLD,
        },
        "resolved_benchmark_relative": len(resolved),
        "resolved_legacy_raw": len(legacy),
        "benchmark_relative_win_rate": (round(_win_rate(resolved), 4) if resolved else None),
        "flat_rate": (round(sum(1 for p in resolved if p.get("outcome") == "FLAT") / len(resolved), 4)
                      if resolved else None),
        "mean_excess_return": (
            round(statistics.fmean([p["excess_vs_benchmark"] for p in resolved
                                    if isinstance(p.get("excess_vs_benchmark"), (int, float))]), 4)
            if any(isinstance(p.get("excess_vs_benchmark"), (int, float)) for p in resolved)
            else None),
        "legacy_raw_win_rate": (round(_win_rate(legacy), 4) if legacy else None),
        "calibration": calibration,
        "concentration_window": concentration,
        "slippage": slippage,
        "sample_sufficient_for_rubric_change": sample_ok,
        "min_resolved_for_rubric_change": schema.MIN_RESOLVED_FOR_RUBRIC_CHANGE,
        "sector_penalties": sector_penalties,
        "signal_penalties": signal_penalties,
        "confidence_cap": schema.MAX_CONFIDENCE,
        "overconfidence_warning": overconfidence_warning,
        "due_for_resolution": due_for_resolution(),
        "notes": notes,
    }


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    print(json.dumps(compute_adjustments(n), indent=2))
