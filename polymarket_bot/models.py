"""Core dataclasses for markets, prices, positions, and trade events."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass
class Market:
    market_id: str
    question: str
    end_time: datetime
    volume_usd: float
    category: str
    yes_token_id: str
    no_token_id: str
    active: bool = True


@dataclass
class PricePoint:
    ts: datetime
    yes: float
    no: float


@dataclass
class Position:
    market_id: str
    question: str
    side: str
    category: str
    entry_ts: datetime
    entry_price: float
    size_dollars: float
    shares: float
    stop_loss_cents: float


@dataclass
class TradeEvent:
    market_id: str
    question: str
    category: str
    side: str
    event_type: str
    ts: datetime
    price: float
    size_dollars: float
    shares: float
    pnl: float = 0.0
    reason: str = ""

    def to_json(self) -> dict:
        payload = asdict(self)
        payload["ts"] = self.ts.isoformat()
        return payload
