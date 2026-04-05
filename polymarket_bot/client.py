"""Polymarket API client with resilient parsing and retries."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import requests

from .config import BotConfig
from .models import Market, PricePoint


class PolymarketClient:
    def __init__(self, cfg: BotConfig):
        self.cfg = cfg
        self.session = requests.Session()

    def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.session.get(url, params=params, timeout=self.cfg.requests_timeout_seconds)
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:  # pragma: no cover - network protection
                last_error = exc
                time.sleep(0.75 * (attempt + 1))
        if last_error is None:
            raise RuntimeError("Unexpected error during request")
        raise last_error

    @staticmethod
    def _parse_end_time(raw: dict[str, Any]) -> datetime:
        for key in ("endDate", "endTime", "end_date_iso", "end_time"):
            val = raw.get(key)
            if not val:
                continue
            if isinstance(val, (int, float)):
                return datetime.fromtimestamp(float(val), tz=timezone.utc)
            if isinstance(val, str):
                return datetime.fromisoformat(val.replace("Z", "+00:00"))
        raise ValueError("Market has no parseable end time")

    @staticmethod
    def _get_outcome_token_ids(raw: dict[str, Any]) -> tuple[str, str]:
        # Most gamma responses include outcome tokens in "tokens".
        tokens = raw.get("tokens") or []
        yes_id, no_id = "", ""
        for token in tokens:
            outcome = str(token.get("outcome", "")).strip().lower()
            token_id = str(token.get("token_id") or token.get("tokenId") or "")
            if outcome == "yes" and token_id:
                yes_id = token_id
            if outcome == "no" and token_id:
                no_id = token_id
        # fallback using outcomePrices ordering
        if not yes_id:
            yes_id = str(raw.get("yesTokenId") or "")
        if not no_id:
            no_id = str(raw.get("noTokenId") or "")
        return yes_id, no_id

    def fetch_open_markets(self) -> list[Market]:
        payload = self._get(f"{self.cfg.gamma_base_url}/markets", params={"closed": "false", "limit": 2000})
        rows = payload if isinstance(payload, list) else payload.get("data", [])
        markets: list[Market] = []

        for raw in rows:
            try:
                end_time = self._parse_end_time(raw)
            except Exception:
                continue
            yes_token_id, no_token_id = self._get_outcome_token_ids(raw)
            if not yes_token_id or not no_token_id:
                continue

            volume = raw.get("volume") or raw.get("volumeNum") or raw.get("liquidityNum") or 0
            category = str(raw.get("category") or raw.get("slug") or "uncategorized")
            market = Market(
                market_id=str(raw.get("id") or raw.get("conditionId") or raw.get("slug") or ""),
                question=str(raw.get("question") or raw.get("title") or ""),
                end_time=end_time,
                volume_usd=float(volume),
                category=category,
                yes_token_id=yes_token_id,
                no_token_id=no_token_id,
                active=bool(raw.get("active", True)),
            )
            if market.market_id:
                markets.append(market)

        return markets

    def fetch_price(self, token_id: str) -> float:
        # CLOB midpoint endpoint.
        payload = self._get(f"{self.cfg.clob_base_url}/midpoint", params={"token_id": token_id})
        mid = payload.get("mid") if isinstance(payload, dict) else payload
        return float(mid)

    def fetch_market_price_point(self, market: Market, ts: datetime | None = None) -> PricePoint:
        yes_price = self.fetch_price(market.yes_token_id)
        no_price = self.fetch_price(market.no_token_id)
        return PricePoint(ts=ts or datetime.now(timezone.utc), yes=yes_price, no=no_price)
