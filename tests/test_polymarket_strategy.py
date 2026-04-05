import unittest
from datetime import datetime, timedelta, timezone

from polymarket_bot.config import BotConfig
from polymarket_bot.models import Market, PricePoint
from polymarket_bot.strategy import entry_signal_from_price, select_markets_for_next_24h, stop_loss_hit


def _market(mid: str, hours: int, category: str, q: str, active: bool = True):
    return Market(
        market_id=mid,
        question=q,
        end_time=datetime.now(timezone.utc) + timedelta(hours=hours),
        volume_usd=150000,
        category=category,
        yes_token_id="y",
        no_token_id="n",
        active=active,
    )


class StrategyTests(unittest.TestCase):
    def test_select_filters_crypto_and_horizon(self):
        cfg = BotConfig()
        markets = [
            _market("1", 2, "politics", "Will bill pass?"),
            _market("2", 2, "crypto", "Will BTC > 120k?"),
            _market("3", 40, "sports", "Will team win?"),
        ]
        selected = select_markets_for_next_24h(markets, cfg)
        ids = [m.market_id for m in selected]
        self.assertEqual(ids, ["1"])

    def test_entry_trigger_yes_and_no(self):
        cfg = BotConfig()
        yes_point = PricePoint(ts=datetime.now(timezone.utc), yes=0.951, no=0.049)
        no_point = PricePoint(ts=datetime.now(timezone.utc), yes=0.03, no=0.97)

        sig_yes = entry_signal_from_price(yes_point, cfg)
        sig_no = entry_signal_from_price(no_point, cfg)

        self.assertIsNotNone(sig_yes)
        self.assertEqual(sig_yes.side, "YES")
        self.assertIsNotNone(sig_no)
        self.assertEqual(sig_no.side, "NO")

    def test_stop_loss_hit(self):
        cfg = BotConfig()
        point = PricePoint(ts=datetime.now(timezone.utc), yes=0.69, no=0.31)
        hit, px = stop_loss_hit("YES", point, cfg)
        self.assertTrue(hit)
        self.assertEqual(px, 0.69)


if __name__ == "__main__":
    unittest.main()
