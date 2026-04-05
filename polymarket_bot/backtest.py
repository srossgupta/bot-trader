"""Backtesting via local snapshot replay (fast and deterministic)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from .config import BotConfig
from .models import Market, PricePoint
from .strategy import entry_signal_from_price, stop_loss_hit


class BacktestResult(dict):
    pass


def _row_to_market(row: dict) -> Market:
    return Market(
        market_id=row["market_id"],
        question=row.get("question", ""),
        end_time=datetime.fromisoformat(row["end_time"]),
        volume_usd=150000,
        category=row.get("category", "unknown"),
        yes_token_id="yes",
        no_token_id="no",
    )


def run_snapshot_backtest(cfg: BotConfig, snapshots: list[dict]) -> BacktestResult:
    by_market: dict[str, list[dict]] = defaultdict(list)
    for row in snapshots:
        by_market[row["market_id"]].append(row)

    total_pnl = 0.0
    wins = 0
    losses = 0
    by_category: dict[str, dict[str, float]] = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})

    for market_id, rows in by_market.items():
        rows.sort(key=lambda r: r["ts"])
        market = _row_to_market(rows[0])
        entered = None

        for row in rows:
            point = PricePoint(
                ts=datetime.fromisoformat(row["ts"]),
                yes=float(row["yes"]),
                no=float(row["no"]),
            )
            if not entered:
                signal = entry_signal_from_price(point, cfg)
                if signal:
                    entered = {"side": signal.side, "entry": signal.price, "size": cfg.strategy.max_dollars_per_market}
                continue

            hit, current = stop_loss_hit(entered["side"], point, cfg)
            if hit:
                pnl = (entered["size"] / entered["entry"]) * current - entered["size"]
                total_pnl += pnl
                losses += 1
                by_category[market.category]["trades"] += 1
                by_category[market.category]["pnl"] += pnl
                entered = None
                break

        if entered:
            last = rows[-1]
            exit_price = float(last["yes"] if entered["side"] == "YES" else last["no"])
            pnl = (entered["size"] / entered["entry"]) * exit_price - entered["size"]
            total_pnl += pnl
            wins += 1 if pnl > 0 else 0
            losses += 1 if pnl <= 0 else 0
            by_category[market.category]["trades"] += 1
            by_category[market.category]["wins"] += 1 if pnl > 0 else 0
            by_category[market.category]["pnl"] += pnl

    total_trades = wins + losses
    win_rate = (wins / total_trades) if total_trades else 0.0
    return BacktestResult(
        {
            "trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 4),
            "pnl": round(total_pnl, 2),
            "category_stats": by_category,
        }
    )
