"""CLI entrypoint for Polymarket paper bot."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta

from .config import load_config
from .engine import run_backtest, run_daily_once


def cmd_backtest() -> None:
    result = run_backtest()
    print(json.dumps(result, indent=2))


def cmd_paper_once() -> None:
    summary = run_daily_once()
    print(json.dumps(summary, indent=2))


def cmd_run_loop() -> None:
    cfg = load_config()
    print("Starting daily loop for Polymarket paper bot...")

    while True:
        now_local = datetime.now(cfg.local_tz)
        target = now_local.replace(
            hour=cfg.strategy.scan_hour_local,
            minute=cfg.strategy.scan_minute_local,
            second=0,
            microsecond=0,
        )
        if target <= now_local:
            target += timedelta(days=1)

        wait = (target - now_local).total_seconds()
        print(f"Sleeping until next scan at {target.isoformat()} ({wait/60:.1f} min)")
        time.sleep(max(wait, 1.0))

        summary = run_daily_once(cfg)
        print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Polymarket high-probability paper trading bot")
    parser.add_argument("--backtest", action="store_true", help="Run backtest from snapshots")
    parser.add_argument("--paper-once", action="store_true", help="Run one full scan-to-close paper cycle")
    parser.add_argument("--run-loop", action="store_true", help="Run forever on fixed daily schedule")
    args = parser.parse_args()

    if args.backtest:
        cmd_backtest()
    elif args.paper_once:
        cmd_paper_once()
    elif args.run_loop:
        cmd_run_loop()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
