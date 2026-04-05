"""Trading rules for market selection, entries, and stop-loss handling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import BotConfig
from .models import Market, PricePoint


@dataclass
class EntrySignal:
    side: str
    price: float
    reason: str


def is_crypto_market(market: Market, cfg: BotConfig) -> bool:
    text = f"{market.category} {market.question}".lower()
    return any(kw in text for kw in cfg.strategy.disallowed_category_keywords)


def select_markets_for_next_24h(markets: list[Market], cfg: BotConfig, now: datetime | None = None) -> list[Market]:
    now_utc = now or datetime.now(timezone.utc)
    horizon = now_utc + timedelta(hours=cfg.strategy.max_scan_horizon_hours)
    lowered_pref = {c.lower() for c in cfg.preferred_categories}

    selected = []
    for market in markets:
        if not market.active:
            continue
        if is_crypto_market(market, cfg):
            continue
        if lowered_pref:
            if market.category.lower() not in lowered_pref:
                continue
        if not (now_utc < market.end_time <= horizon):
            continue
        selected.append(market)

    return sorted(selected, key=lambda m: m.end_time)


def should_wake_for_market(market: Market, cfg: BotConfig, now: datetime | None = None) -> bool:
    now_utc = now or datetime.now(timezone.utc)
    wake_time = market.end_time - timedelta(minutes=cfg.strategy.wake_minutes_before_close)
    return now_utc >= wake_time


def eligible_for_tracking(market: Market, cfg: BotConfig) -> bool:
    return market.volume_usd >= cfg.strategy.min_volume_usd


def entry_signal_from_price(point: PricePoint, cfg: BotConfig) -> EntrySignal | None:
    threshold = cfg.strategy.entry_threshold_cents / 100.0

    if point.yes >= threshold:
        return EntrySignal(side="YES", price=point.yes, reason=f"YES >= {cfg.strategy.entry_threshold_cents:.0f}c")
    if point.no >= threshold:
        return EntrySignal(side="NO", price=point.no, reason=f"NO >= {cfg.strategy.entry_threshold_cents:.0f}c")
    return None


def stop_loss_hit(side: str, point: PricePoint, cfg: BotConfig) -> tuple[bool, float]:
    stop = cfg.strategy.stop_loss_cents / 100.0
    current = point.yes if side == "YES" else point.no
    return current < stop, current
