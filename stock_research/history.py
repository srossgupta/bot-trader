"""
Persistence for nightly stock research runs.

Each run is one JSON line in data/stock_research/runs.jsonl:
  {
    "run_date": "2026-05-06",
    "picks": [
      {
        "ticker": "MU",
        "company": "Micron Technology",
        "direction": "UP",           # "UP" | "DOWN"
        "confidence": 90,            # 0-100
        "sector": "Semiconductors",
        "catalyst": "...",
        "signals_hit": ["forum_sentiment", "fundamental_catalyst", ...],
        "price_at_pick": 265.0,      # approx closing price on run date
        "price_later": null,         # filled in by a later run
        "pct_change": null,          # price_later / price_at_pick - 1
        "outcome": null              # "WIN" | "LOSS" (null until evaluated)
      },
      ...
    ]
  }

CLI:
  python -m stock_research.history load_recent [N]
  python -m stock_research.history save_run '<json>'
  python -m stock_research.history mark_outcome <run_date> <ticker> <current_price>
"""

from __future__ import annotations

import json
import os
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, "data", "stock_research")
RUNS_FILE = os.path.join(DATA_DIR, "runs.jsonl")

os.makedirs(DATA_DIR, exist_ok=True)


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


def save_run(run: dict) -> None:
    """Append run. If run_date already exists, replace it (idempotent)."""
    runs = load_all_runs()
    runs = [r for r in runs if r["run_date"] != run["run_date"]]
    runs.append(run)
    _rewrite(runs)


def mark_outcome(run_date: str, ticker: str, current_price: float) -> None:
    """Fill in price_later, pct_change, and outcome for one past pick."""
    runs = load_all_runs()
    changed = False
    for run in runs:
        if run["run_date"] != run_date:
            continue
        for pick in run.get("picks", []):
            if pick["ticker"] != ticker:
                continue
            if pick.get("outcome"):
                return  # already evaluated, nothing to do
            pick["price_later"] = current_price
            price_at = pick.get("price_at_pick")
            if price_at and price_at > 0:
                pct = (current_price - price_at) / price_at
                pick["pct_change"] = round(pct, 4)
                if pick.get("direction", "UP") == "UP":
                    pick["outcome"] = "WIN" if pct > 0 else "LOSS"
                else:
                    pick["outcome"] = "WIN" if pct < 0 else "LOSS"
            changed = True
            break
        if changed:
            break
    if changed:
        _rewrite(runs)


def _rewrite(runs: list[dict]) -> None:
    with open(RUNS_FILE, "w", encoding="utf-8") as f:
        for run in runs:
            f.write(json.dumps(run) + "\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "load_recent":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        print(json.dumps(load_recent(n), indent=2))

    elif cmd == "save_run":
        run = json.loads(sys.argv[2])
        save_run(run)
        print(f"Saved run for {run['run_date']} ({len(run.get('picks', []))} picks)")

    elif cmd == "mark_outcome":
        if len(sys.argv) < 5:
            print("Usage: mark_outcome <run_date> <ticker> <current_price>")
            sys.exit(1)
        mark_outcome(sys.argv[2], sys.argv[3], float(sys.argv[4]))
        print(f"Marked outcome for {sys.argv[3]} on {sys.argv[2]} at ${sys.argv[4]}")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    _cli()
