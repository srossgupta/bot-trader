"""Configuration and persistent adaptive parameters for the Polymarket bot."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import time
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, "data", "polymarket")
os.makedirs(DATA_DIR, exist_ok=True)

ADAPTIVE_STATE_FILE = os.path.join(DATA_DIR, "adaptive_state.json")
WATCHLIST_FILE = os.path.join(DATA_DIR, "watchlist.json")
SNAPSHOT_FILE = os.path.join(DATA_DIR, "price_snapshots.jsonl")
TRADES_FILE = os.path.join(DATA_DIR, "paper_trades.jsonl")
METRICS_FILE = os.path.join(DATA_DIR, "metrics_history.jsonl")


@dataclass
class StrategyParams:
    scan_hour_local: int = 8
    scan_minute_local: int = 0
    wake_minutes_before_close: int = 6
    max_scan_horizon_hours: int = 24

    min_volume_usd: float = 100_000.0
    entry_threshold_cents: float = 95.0
    stop_loss_cents: float = 70.0

    max_dollars_per_market: float = 100.0
    poll_seconds: float = 1.5
    min_time_to_close_seconds: int = 30

    disallowed_category_keywords: list[str] = field(
        default_factory=lambda: ["crypto", "bitcoin", "ethereum", "solana"]
    )


@dataclass
class BotConfig:
    timezone: str = "America/Los_Angeles"
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"
    requests_timeout_seconds: int = 20

    starting_cash: float = 2_000.0
    max_open_positions: int = 15

    strategy: StrategyParams = field(default_factory=StrategyParams)

    # self-correction bounds
    min_entry_cents: float = 90.0
    max_entry_cents: float = 98.0
    min_stop_cents: float = 60.0
    max_stop_cents: float = 85.0
    min_wake_minutes: int = 3
    max_wake_minutes: int = 15

    # adaptation behavior
    adaptation_trade_window: int = 80
    min_trades_for_adaptation: int = 15
    target_win_rate: float = 0.62
    adaptation_step_cents: float = 1.0

    # category behavior
    min_category_samples: int = 5
    max_preferred_categories: int = 6
    preferred_categories: list[str] = field(default_factory=list)

    @property
    def local_tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def scan_time(self) -> time:
        return time(self.strategy.scan_hour_local, self.strategy.scan_minute_local)


def _strategy_from_dict(data: dict[str, Any]) -> StrategyParams:
    params = StrategyParams()
    for key, value in data.items():
        if hasattr(params, key):
            setattr(params, key, value)
    return params


def load_config() -> BotConfig:
    """Load base config, then overlay adaptive state if available."""
    cfg = BotConfig()

    if os.path.exists(ADAPTIVE_STATE_FILE):
        try:
            with open(ADAPTIVE_STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            strategy_overrides = state.get("strategy", {})
            cfg.strategy = _strategy_from_dict({**asdict(cfg.strategy), **strategy_overrides})
            cfg.preferred_categories = state.get("preferred_categories", [])
        except (OSError, json.JSONDecodeError):
            pass

    return cfg


def save_adaptive_strategy(params: StrategyParams, preferred_categories: list[str]) -> None:
    payload = {
        "strategy": asdict(params),
        "preferred_categories": preferred_categories,
    }
    with open(ADAPTIVE_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
