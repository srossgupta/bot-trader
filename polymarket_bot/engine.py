"""Runtime orchestration for scanning, monitoring, and paper execution."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from .adaptive import adapt_strategy
from .backtest import run_snapshot_backtest
from .client import PolymarketClient
from .config import BotConfig, load_config
from .paper import PaperPortfolio
from .storage import append_metrics, append_snapshot, load_snapshots, load_trade_events, save_watchlist
from .strategy import eligible_for_tracking, entry_signal_from_price, select_markets_for_next_24h, should_wake_for_market, stop_loss_hit


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def scan_watchlist(client: PolymarketClient, cfg: BotConfig, now: datetime | None = None) -> list:
    markets = client.fetch_open_markets()
    selected = select_markets_for_next_24h(markets, cfg, now=now)
    save_watchlist(selected)
    return selected


def monitor_market_until_close(
    client: PolymarketClient,
    portfolio: PaperPortfolio,
    market,
    cfg: BotConfig,
    now_fn: Callable[[], datetime] = _utcnow,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict:
    stats = {"market_id": market.market_id, "question": market.question, "entered": False, "stopped": False}
    if not eligible_for_tracking(market, cfg):
        stats["skipped"] = f"volume<{cfg.strategy.min_volume_usd}"
        return stats

    last_point = None
    while now_fn() < market.end_time:
        point = client.fetch_market_price_point(market, ts=now_fn())
        last_point = point
        append_snapshot(market, point)

        if market.market_id not in portfolio.open_positions:
            signal = entry_signal_from_price(point, cfg)
            if signal:
                pos = portfolio.open_position(market, signal.side, signal.price, signal.reason)
                if pos:
                    stats["entered"] = True
                    stats["side"] = signal.side
                    stats["entry_price"] = signal.price

        if market.market_id in portfolio.open_positions:
            side = portfolio.open_positions[market.market_id].side
            hit, px = stop_loss_hit(side, point, cfg)
            if hit:
                portfolio.close_position(market, point, reason=f"stop_loss<{cfg.strategy.stop_loss_cents:.0f}c")
                stats["stopped"] = True
                stats["stop_price"] = px
                return stats

        seconds_to_close = (market.end_time - now_fn()).total_seconds()
        if seconds_to_close <= cfg.strategy.min_time_to_close_seconds:
            break
        sleeper(cfg.strategy.poll_seconds)

    if market.market_id in portfolio.open_positions and last_point is not None:
        portfolio.close_position(market, last_point, reason="market_expired", event_type="FORCED_CLOSE_AT_EXPIRY")
        stats["forced_close"] = True

    return stats


def run_daily_once(cfg: BotConfig | None = None) -> dict:
    cfg = cfg or load_config()
    client = PolymarketClient(cfg)
    portfolio = PaperPortfolio(cfg)

    now = _utcnow()
    watchlist = scan_watchlist(client, cfg, now=now)

    pending = [m for m in watchlist if m.end_time > now]
    run_stats = []

    while pending:
        pending.sort(key=lambda m: m.end_time)
        current = _utcnow()
        due = [m for m in pending if should_wake_for_market(m, cfg, now=current)]

        if not due:
            next_market = pending[0]
            wake_at = next_market.end_time - timedelta(minutes=cfg.strategy.wake_minutes_before_close)
            sleep_seconds = max(1.0, min(30.0, (wake_at - current).total_seconds()))
            time.sleep(sleep_seconds)
            continue

        # process all due markets; supports same close-time clusters
        for market in due:
            stats = monitor_market_until_close(client, portfolio, market, cfg)
            run_stats.append(stats)
            pending = [m for m in pending if m.market_id != market.market_id]

    trade_rows = load_trade_events()
    adaptation = adapt_strategy(cfg, trade_rows)

    summary = {
        "timestamp": _utcnow().isoformat(),
        "watchlist_count": len(watchlist),
        "processed_count": len(run_stats),
        "open_positions": len(portfolio.open_positions),
        "cash": round(portfolio.cash, 2),
        "run_stats": run_stats,
        "adaptation": adaptation,
    }
    append_metrics(summary)
    return summary


def build_synthetic_snapshots() -> list[dict]:
    base = _utcnow().replace(second=0, microsecond=0)
    rows = []
    # Market A: YES crosses 95c and finishes strong
    for i, yes in enumerate([0.92, 0.95, 0.96, 0.97, 0.99]):
        rows.append(
            {
                "market_id": "mkt_A",
                "question": "Will Team A win?",
                "category": "sports",
                "end_time": (base + timedelta(minutes=10)).isoformat(),
                "ts": (base + timedelta(seconds=i * 60)).isoformat(),
                "yes": yes,
                "no": 1 - yes,
            }
        )

    # Market B: NO crosses 95c but then drops below stop-loss
    for i, no in enumerate([0.94, 0.96, 0.91, 0.75, 0.68]):
        rows.append(
            {
                "market_id": "mkt_B",
                "question": "Will Candidate X lose?",
                "category": "politics",
                "end_time": (base + timedelta(minutes=11)).isoformat(),
                "ts": (base + timedelta(seconds=i * 55)).isoformat(),
                "yes": 1 - no,
                "no": no,
            }
        )
    return rows


def run_backtest(cfg: BotConfig | None = None) -> dict:
    cfg = cfg or load_config()
    snapshots = load_snapshots()
    source = "recorded_snapshots"
    if not snapshots:
        snapshots = build_synthetic_snapshots()
        source = "synthetic_bootstrap"

    result = run_snapshot_backtest(cfg, snapshots)
    payload = {
        "source": source,
        "result": {
            "trades": result["trades"],
            "wins": result["wins"],
            "losses": result["losses"],
            "win_rate": result["win_rate"],
            "pnl": result["pnl"],
        },
    }
    append_metrics({"timestamp": _utcnow().isoformat(), "backtest": payload})
    return payload
