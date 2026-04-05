"""Paper portfolio and execution helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from .config import BotConfig
from .models import Market, Position, PricePoint, TradeEvent
from .storage import append_trade


@dataclass
class PaperPortfolio:
    cfg: BotConfig
    cash: float = 0.0
    open_positions: dict[str, Position] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cash <= 0:
            self.cash = self.cfg.starting_cash

    def can_open_new(self) -> bool:
        return len(self.open_positions) < self.cfg.max_open_positions and self.cash > 1.0

    def open_position(self, market: Market, side: str, price: float, reason: str) -> Position | None:
        if market.market_id in self.open_positions:
            return None
        if not self.can_open_new():
            return None

        allocation = min(self.cfg.strategy.max_dollars_per_market, self.cash)
        if allocation < 1:
            return None

        shares = allocation / max(price, 1e-6)
        pos = Position(
            market_id=market.market_id,
            question=market.question,
            side=side,
            category=market.category,
            entry_ts=datetime.now(timezone.utc),
            entry_price=price,
            size_dollars=allocation,
            shares=shares,
            stop_loss_cents=self.cfg.strategy.stop_loss_cents,
        )
        self.open_positions[market.market_id] = pos
        self.cash -= allocation

        append_trade(
            TradeEvent(
                market_id=market.market_id,
                question=market.question,
                category=market.category,
                side=side,
                event_type="BUY_LIMIT_FILL",
                ts=pos.entry_ts,
                price=price,
                size_dollars=allocation,
                shares=shares,
                reason=reason,
            )
        )
        return pos

    def close_position(self, market: Market, point: PricePoint, reason: str, event_type: str = "SELL_MARKET") -> TradeEvent | None:
        pos = self.open_positions.get(market.market_id)
        if not pos:
            return None

        exit_price = point.yes if pos.side == "YES" else point.no
        proceeds = pos.shares * exit_price
        pnl = proceeds - pos.size_dollars
        self.cash += proceeds
        del self.open_positions[market.market_id]

        event = TradeEvent(
            market_id=market.market_id,
            question=market.question,
            category=market.category,
            side=pos.side,
            event_type=event_type,
            ts=point.ts,
            price=exit_price,
            size_dollars=proceeds,
            shares=pos.shares,
            pnl=pnl,
            reason=reason,
        )
        append_trade(event)
        return event

    def mark_to_market(self, points: dict[str, PricePoint]) -> float:
        value = self.cash
        for market_id, pos in self.open_positions.items():
            point = points.get(market_id)
            if not point:
                continue
            price = point.yes if pos.side == "YES" else point.no
            value += pos.shares * price
        return value

    def to_json(self) -> dict:
        return {
            "cash": self.cash,
            "open_positions": {mid: asdict(p) for mid, p in self.open_positions.items()},
        }
