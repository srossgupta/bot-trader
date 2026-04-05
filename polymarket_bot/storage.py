"""Persistence helpers for watchlists, snapshots, and paper trade logs."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime

from .config import METRICS_FILE, SNAPSHOT_FILE, TRADES_FILE, WATCHLIST_FILE
from .models import Market, PricePoint, TradeEvent


def save_watchlist(markets: list[Market]) -> None:
    payload = []
    for market in markets:
        row = asdict(market)
        row["end_time"] = market.end_time.isoformat()
        payload.append(row)
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def load_watchlist() -> list[Market]:
    if not os.path.exists(WATCHLIST_FILE):
        return []
    with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
        rows = json.load(f)
    markets = []
    for row in rows:
        markets.append(
            Market(
                market_id=row["market_id"],
                question=row["question"],
                end_time=datetime.fromisoformat(row["end_time"]),
                volume_usd=row["volume_usd"],
                category=row["category"],
                yes_token_id=row["yes_token_id"],
                no_token_id=row["no_token_id"],
                active=row.get("active", True),
            )
        )
    return markets


def append_snapshot(market: Market, point: PricePoint) -> None:
    payload = {
        "market_id": market.market_id,
        "question": market.question,
        "category": market.category,
        "end_time": market.end_time.isoformat(),
        "ts": point.ts.isoformat(),
        "yes": point.yes,
        "no": point.no,
    }
    with open(SNAPSHOT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def append_trade(event: TradeEvent) -> None:
    with open(TRADES_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event.to_json()) + "\n")


def append_metrics(metrics: dict) -> None:
    with open(METRICS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(metrics) + "\n")


def load_trade_events() -> list[dict]:
    if not os.path.exists(TRADES_FILE):
        return []
    rows = []
    with open(TRADES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def load_snapshots() -> list[dict]:
    if not os.path.exists(SNAPSHOT_FILE):
        return []
    rows = []
    with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows
