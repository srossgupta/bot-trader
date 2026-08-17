"""
Append-only ledger for nightly stock research runs.

One JSON line per run in data/stock_research/runs.jsonl. Every pick carries its
own entry price, horizon, resolution price and a `resolved` done-flag, so a pick
is graded exactly once and never re-graded.

Pick record (schema v2):
  {
    "ticker": "MU",
    "company": "Micron Technology",
    "direction": "UP",                    # UP | DOWN
    "confidence": 88,                     # 60-90, capped (see schema.MAX_CONFIDENCE)
    "sector": "Semiconductors",
    "sector_bucket": "AI/Semis/Tech",     # derived
    "catalyst": "...",
    "signals_hit": ["forum_sentiment", ...],
    "price_at_pick": 265.0,               # verified, never estimated
    "price_source": "verified_close",
    "price_asof": "2026-08-17",
    "picked_at": "2026-08-17T21:30:00Z",  # when the email went out
    "benchmark_ticker": "QQQ",
    "benchmark_at_pick": 601.2,
    "run_up_10d_pct": 0.31,               # anti-chasing: trailing 10-session move
    "horizon_trading_days": 3,
    "resolve_on": "2026-08-20",           # derived, trading days
    "next_open_price": 267.1,             # slippage measurement, next session
    "slippage_pct": 0.0079,
    "resolution_price": null,
    "benchmark_at_resolution": null,
    "pct_change": null,
    "benchmark_pct_change": null,
    "excess_vs_benchmark": null,          # what actually decides the outcome
    "outcome": null,                      # WIN | LOSS | FLAT, set once
    "resolved": false
  }

CLI:
  python -m stock_research.history load_recent [N]
  python -m stock_research.history save_run '<json>'
  python -m stock_research.history due [YYYY-MM-DD]
  python -m stock_research.history resolve <run_date> <ticker> <price> <benchmark_price> [asof]
  python -m stock_research.history record_next_open <run_date> <ticker> <open_price> [date]
  python -m stock_research.history ledger [N]
  python -m stock_research.history migrate
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys

from . import schema
from .trading_calendar import add_trading_days, parse_date

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, "data", "stock_research")
RUNS_FILE = os.path.join(DATA_DIR, "runs.jsonl")

os.makedirs(DATA_DIR, exist_ok=True)


class LedgerError(Exception):
    """Raised when an operation would corrupt or re-write ledger history."""


# ── I/O ───────────────────────────────────────────────────────────────────────

def load_all_runs() -> list[dict]:
    if not os.path.exists(RUNS_FILE):
        return []
    runs = []
    with open(RUNS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                runs.append(json.loads(line))
    return runs


def load_recent(n: int = 3) -> list[dict]:
    """Return the last N runs, oldest first."""
    return load_all_runs()[-n:]


def _rewrite(runs: list[dict]) -> None:
    runs = sorted(runs, key=lambda r: r["run_date"])
    tmp = RUNS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for run in runs:
            f.write(json.dumps(run) + "\n")
    os.replace(tmp, RUNS_FILE)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _find_pick(runs: list[dict], run_date: str, ticker: str) -> dict:
    for run in runs:
        if run.get("run_date") != run_date:
            continue
        for pick in run.get("picks", []):
            if pick.get("ticker") == ticker:
                return pick
        raise LedgerError(f"No pick {ticker} in run {run_date}")
    raise LedgerError(f"No run recorded for {run_date}")


# ── Writing picks ─────────────────────────────────────────────────────────────

def save_run(run: dict) -> dict:
    """
    Validate and append a run. Rejects the whole run if any pick is malformed,
    unverified, or over the confidence cap — a bad anchor poisons every future
    evaluation, so it never reaches the ledger.
    """
    run_date = run.get("run_date")
    errors = schema.validate_run_date(run_date)

    picks = run.get("picks") or []
    if not isinstance(picks, list):
        errors.append("'picks' must be a list")
        picks = []
    for pick in picks:
        errors.extend(schema.validate_pick(pick))

    tickers = [p.get("ticker") for p in picks]
    dupes = {t for t in tickers if tickers.count(t) > 1}
    if dupes:
        errors.append(f"duplicate tickers in one run: {sorted(dupes)}")

    existing = load_all_runs()
    prior = next((r for r in existing if r.get("run_date") == run_date), None)
    if prior:
        resolved = [p["ticker"] for p in prior.get("picks", []) if p.get("resolved")]
        if resolved:
            errors.append(
                f"run {run_date} already exists and has resolved picks {resolved} — "
                "the ledger is append-only; resolved history is never rewritten"
            )

    if errors:
        raise LedgerError("Run rejected:\n  - " + "\n  - ".join(errors))

    normalized = [schema.normalize_pick(p, run_date) for p in picks]
    new_run = {
        "run_date": run_date,
        "schema_version": schema.SCHEMA_VERSION,
        "saved_at": _now(),
        "benchmark_ticker": schema.BENCHMARK_TICKER,
        "picks": normalized,
    }

    runs = [r for r in existing if r.get("run_date") != run_date]
    runs.append(new_run)
    _rewrite(runs)

    buckets: dict[str, int] = {}
    for pick in normalized:
        buckets[pick["sector_bucket"]] = buckets.get(pick["sector_bucket"], 0) + 1

    return {
        "saved": run_date,
        "picks": len(normalized),
        "replaced_existing": prior is not None,
        "resolve_on": sorted({p["resolve_on"] for p in normalized}),
        "sector_buckets": buckets,
        "chase_flagged": [p["ticker"] for p in normalized if p["chase_flag"]],
    }


# ── Resolution ────────────────────────────────────────────────────────────────

def due_for_resolution(as_of: str | dt.date | None = None) -> list[dict]:
    """Unresolved picks whose horizon has elapsed, oldest first."""
    today = parse_date(as_of) if as_of else dt.date.today()
    due: list[dict] = []
    for run in load_all_runs():
        for pick in run.get("picks", []):
            if pick.get("resolved") or pick.get("outcome"):
                continue
            if not schema.is_v2(pick):
                due.append({
                    "run_date": run["run_date"],
                    "ticker": pick.get("ticker"),
                    "blocked": "legacy pick (schema v1) — no benchmark entry price; "
                               "backfill with set_benchmark_entry or leave unresolved",
                })
                continue
            resolve_on = pick.get("resolve_on")
            if resolve_on and parse_date(resolve_on) > today:
                continue
            due.append({
                "run_date": run["run_date"],
                "ticker": pick["ticker"],
                "direction": pick["direction"],
                "confidence": pick.get("confidence"),
                "price_at_pick": pick["price_at_pick"],
                "benchmark_ticker": pick.get("benchmark_ticker", schema.BENCHMARK_TICKER),
                "benchmark_at_pick": pick.get("benchmark_at_pick"),
                "resolve_on": resolve_on,
                "lookup": f"verified close for {pick['ticker']} and "
                          f"{pick.get('benchmark_ticker', schema.BENCHMARK_TICKER)} on {resolve_on}",
            })
    return due


def resolve(run_date: str, ticker: str, price: float, benchmark_price: float,
            as_of: str | None = None) -> dict:
    """
    Grade one pick, exactly once, benchmark-relative.

    Refuses to touch a pick that is already resolved, and refuses to resolve
    before the declared horizon has elapsed — a fixed horizon that bends to
    whatever price is convenient is not a fixed horizon.
    """
    runs = load_all_runs()
    pick = _find_pick(runs, run_date, ticker)

    if pick.get("resolved") or pick.get("outcome"):
        raise LedgerError(
            f"{ticker} from {run_date} is already resolved "
            f"(outcome={pick.get('outcome')}, price={pick.get('resolution_price')}). "
            "Picks are graded exactly once."
        )
    if not schema.is_v2(pick):
        raise LedgerError(
            f"{ticker} from {run_date} is a legacy (v1) pick with no benchmark "
            "entry price. Backfill it with set_benchmark_entry first, or leave it."
        )
    if price <= 0 or benchmark_price <= 0:
        raise LedgerError("Resolution prices must be positive verified closes.")

    resolve_on = pick.get("resolve_on")
    as_of_date = parse_date(as_of) if as_of else dt.date.today()
    if resolve_on and as_of_date < parse_date(resolve_on):
        raise LedgerError(
            f"{ticker} from {run_date} resolves on {resolve_on}; "
            f"{as_of_date.isoformat()} is inside the horizon."
        )

    graded = schema.grade(
        pick["direction"], pick["price_at_pick"], price,
        pick["benchmark_at_pick"], benchmark_price,
    )
    pick.update(graded)
    pick["resolution_price"] = price
    pick["benchmark_at_resolution"] = benchmark_price
    pick["resolution_date"] = (as_of or resolve_on or as_of_date.isoformat())
    pick["resolved_at"] = _now()
    pick["resolved"] = True
    _rewrite(runs)

    return {"run_date": run_date, "ticker": ticker, **graded,
            "resolution_date": pick["resolution_date"]}


def set_benchmark_entry(run_date: str, ticker: str, benchmark_price: float,
                        horizon: int | None = None) -> dict:
    """
    Backfill a benchmark entry price (and horizon) onto an open legacy pick so
    it can be graded on the same footing as new ones. Refuses resolved picks.
    """
    runs = load_all_runs()
    pick = _find_pick(runs, run_date, ticker)
    if pick.get("resolved") or pick.get("outcome"):
        raise LedgerError(f"{ticker} from {run_date} is already resolved — history is not rewritten.")
    if benchmark_price <= 0:
        raise LedgerError("Benchmark price must be positive.")

    horizon = horizon or pick.get("horizon_trading_days") or schema.DEFAULT_HORIZON_TRADING_DAYS
    pick["benchmark_ticker"] = pick.get("benchmark_ticker", schema.BENCHMARK_TICKER)
    pick["benchmark_at_pick"] = benchmark_price
    pick["horizon_trading_days"] = horizon
    pick["resolve_on"] = add_trading_days(run_date, horizon).isoformat()
    pick["sector_bucket"] = schema.sector_bucket(pick.get("sector"))
    pick["schema_version"] = schema.SCHEMA_VERSION
    pick.setdefault("price_source", "verified_close")
    pick.setdefault("price_asof", run_date)
    pick["resolved"] = False
    _rewrite(runs)
    return {"run_date": run_date, "ticker": ticker,
            "benchmark_at_pick": benchmark_price, "resolve_on": pick["resolve_on"]}


def record_next_open(run_date: str, ticker: str, open_price: float,
                     open_date: str | None = None) -> dict:
    """
    Record the next session's open against the price quoted in the email.

    This is the anti-chasing measurement: how much of the signal's return is
    already gone by the time the pick could actually be entered.
    """
    runs = load_all_runs()
    pick = _find_pick(runs, run_date, ticker)
    if pick.get("next_open_price") is not None:
        raise LedgerError(f"{ticker} from {run_date} already has a next-open price recorded.")
    if open_price <= 0:
        raise LedgerError("Open price must be positive.")

    entry = pick.get("price_at_pick")
    if not entry:
        raise LedgerError(f"{ticker} from {run_date} has no entry price to compare against.")

    slippage = (open_price - entry) / entry
    if pick.get("direction") == "DOWN":
        slippage = -slippage  # cost is always signed against the position
    pick["next_open_price"] = open_price
    pick["next_open_date"] = open_date or add_trading_days(run_date, 1).isoformat()
    pick["slippage_pct"] = round(slippage, 4)
    _rewrite(runs)
    return {"run_date": run_date, "ticker": ticker, "next_open_price": open_price,
            "slippage_pct": pick["slippage_pct"], "next_open_date": pick["next_open_date"]}


# ── Migration ─────────────────────────────────────────────────────────────────

def migrate() -> dict:
    """
    Stamp pre-ledger history. Legacy picks keep their raw-direction outcomes but
    are marked `grading: "legacy_raw_direction"` so calibration never mixes them
    with benchmark-relative results.
    """
    runs = load_all_runs()
    stamped_runs = graded = open_picks = 0

    for run in runs:
        if run.get("schema_version", 1) >= schema.SCHEMA_VERSION:
            continue
        run["schema_version"] = 1
        stamped_runs += 1
        for pick in run.get("picks", []):
            pick.setdefault("schema_version", 1)
            pick["sector_bucket"] = schema.sector_bucket(pick.get("sector"))
            if pick.get("outcome"):
                pick["resolved"] = True
                pick["grading"] = "legacy_raw_direction"
                pick.setdefault("raw_direction_correct", pick["outcome"] == "WIN")
                graded += 1
            else:
                pick["resolved"] = False
                open_picks += 1

    if stamped_runs:
        _rewrite(runs)
    return {"runs_stamped": stamped_runs, "legacy_graded_picks": graded,
            "legacy_open_picks": open_picks}


def ledger(n: int | None = None) -> list[dict]:
    """Flat ledger view: one row per pick, newest run last."""
    rows: list[dict] = []
    for run in (load_recent(n) if n else load_all_runs()):
        for pick in run.get("picks", []):
            rows.append({
                "run_date": run["run_date"],
                "ticker": pick.get("ticker"),
                "sector_bucket": pick.get("sector_bucket") or schema.sector_bucket(pick.get("sector")),
                "direction": pick.get("direction"),
                "confidence": pick.get("confidence"),
                "entry": pick.get("price_at_pick"),
                "entry_source": pick.get("price_source", "legacy_unverified"),
                "horizon": pick.get("horizon_trading_days"),
                "resolve_on": pick.get("resolve_on"),
                "resolution": pick.get("resolution_price") or pick.get("price_later"),
                "excess_vs_benchmark": pick.get("excess_vs_benchmark"),
                "slippage_pct": pick.get("slippage_pct"),
                "outcome": pick.get("outcome"),
                "resolved": bool(pick.get("resolved") or pick.get("outcome")),
                "grading": pick.get("grading",
                                    "benchmark_relative" if schema.is_v2(pick) else "legacy_raw_direction"),
            })
    return rows


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd, args = sys.argv[1], sys.argv[2:]

    try:
        if cmd == "load_recent":
            print(json.dumps(load_recent(int(args[0]) if args else 3), indent=2))

        elif cmd == "save_run":
            if not args:
                raise LedgerError("Usage: save_run '<json>'")
            print(json.dumps(save_run(json.loads(args[0])), indent=2))

        elif cmd == "due":
            print(json.dumps(due_for_resolution(args[0] if args else None), indent=2))

        elif cmd == "resolve":
            if len(args) < 4:
                raise LedgerError(
                    "Usage: resolve <run_date> <ticker> <price> <benchmark_price> [asof]\n"
                    "Both prices must be verified closes for the resolution date."
                )
            print(json.dumps(resolve(args[0], args[1], float(args[2]), float(args[3]),
                                     args[4] if len(args) > 4 else None), indent=2))

        elif cmd == "mark_outcome":
            raise LedgerError(
                "mark_outcome is retired: grading is benchmark-relative and one-shot.\n"
                "Use: resolve <run_date> <ticker> <price> <benchmark_price> [asof]"
            )

        elif cmd == "set_benchmark_entry":
            if len(args) < 3:
                raise LedgerError("Usage: set_benchmark_entry <run_date> <ticker> <benchmark_price> [horizon]")
            print(json.dumps(set_benchmark_entry(
                args[0], args[1], float(args[2]),
                int(args[3]) if len(args) > 3 else None), indent=2))

        elif cmd == "record_next_open":
            if len(args) < 3:
                raise LedgerError("Usage: record_next_open <run_date> <ticker> <open_price> [date]")
            print(json.dumps(record_next_open(args[0], args[1], float(args[2]),
                                              args[3] if len(args) > 3 else None), indent=2))

        elif cmd == "migrate":
            print(json.dumps(migrate(), indent=2))

        elif cmd == "ledger":
            print(json.dumps(ledger(int(args[0]) if args else None), indent=2))

        else:
            print(f"Unknown command: {cmd}")
            print(__doc__)
            sys.exit(1)

    except LedgerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    _cli()
