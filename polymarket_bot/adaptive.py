"""Self-correction loop for strategy parameters and category selection."""

from __future__ import annotations

from collections import defaultdict

from .config import BotConfig, StrategyParams, save_adaptive_strategy


def adapt_strategy(cfg: BotConfig, closed_trade_events: list[dict]) -> dict:
    trades = [t for t in closed_trade_events if t.get("event_type") in {"SELL_MARKET", "FORCED_CLOSE_AT_EXPIRY"}]
    if len(trades) < cfg.min_trades_for_adaptation:
        return {"adapted": False, "reason": f"need >= {cfg.min_trades_for_adaptation} closed trades"}

    window = trades[-cfg.adaptation_trade_window :]
    win_rate = sum(1 for t in window if t.get("pnl", 0) > 0) / len(window)
    avg_pnl = sum(t.get("pnl", 0) for t in window) / len(window)

    params = cfg.strategy
    step = cfg.adaptation_step_cents

    if win_rate < cfg.target_win_rate:
        params.entry_threshold_cents = min(cfg.max_entry_cents, params.entry_threshold_cents + step)
        params.stop_loss_cents = min(cfg.max_stop_cents, params.stop_loss_cents + step)
        if avg_pnl < 0:
            params.wake_minutes_before_close = max(cfg.min_wake_minutes, params.wake_minutes_before_close - 1)
    else:
        params.entry_threshold_cents = max(cfg.min_entry_cents, params.entry_threshold_cents - step)
        params.stop_loss_cents = max(cfg.min_stop_cents, params.stop_loss_cents - step)
        params.wake_minutes_before_close = min(cfg.max_wake_minutes, params.wake_minutes_before_close + 1)

    by_cat = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    for t in window:
        cat = t.get("category", "unknown")
        by_cat[cat]["trades"] += 1
        by_cat[cat]["wins"] += 1 if t.get("pnl", 0) > 0 else 0
        by_cat[cat]["pnl"] += t.get("pnl", 0)

    ranked = []
    for cat, stats in by_cat.items():
        if stats["trades"] < cfg.min_category_samples:
            continue
        win = stats["wins"] / stats["trades"]
        expectancy = stats["pnl"] / stats["trades"]
        ranked.append((cat, win, expectancy))

    ranked.sort(key=lambda x: (x[2], x[1]), reverse=True)
    preferred_categories = [cat for cat, _, _ in ranked[: cfg.max_preferred_categories]]

    save_adaptive_strategy(params, preferred_categories)

    return {
        "adapted": True,
        "new_entry_cents": params.entry_threshold_cents,
        "new_stop_cents": params.stop_loss_cents,
        "new_wake_minutes": params.wake_minutes_before_close,
        "preferred_categories": preferred_categories,
        "window_trades": len(window),
        "window_win_rate": round(win_rate, 4),
    }
