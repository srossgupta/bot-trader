import unittest

from polymarket_bot.adaptive import adapt_strategy
from polymarket_bot.config import BotConfig


class AdaptiveTests(unittest.TestCase):
    def test_adaptation_requires_minimum_trades(self):
        cfg = BotConfig()
        cfg.min_trades_for_adaptation = 3
        out = adapt_strategy(cfg, [{"event_type": "SELL_MARKET", "pnl": 1}])
        self.assertFalse(out["adapted"])

    def test_adaptation_updates_parameters_when_underperforming(self):
        cfg = BotConfig()
        cfg.min_trades_for_adaptation = 5
        cfg.target_win_rate = 0.7

        events = []
        for i in range(6):
            events.append(
                {
                    "event_type": "SELL_MARKET",
                    "pnl": -5 if i < 5 else 2,
                    "category": "sports" if i % 2 == 0 else "politics",
                }
            )

        before_entry = cfg.strategy.entry_threshold_cents
        before_stop = cfg.strategy.stop_loss_cents
        out = adapt_strategy(cfg, events)

        self.assertTrue(out["adapted"])
        self.assertGreaterEqual(cfg.strategy.entry_threshold_cents, before_entry)
        self.assertGreaterEqual(cfg.strategy.stop_loss_cents, before_stop)


if __name__ == "__main__":
    unittest.main()
