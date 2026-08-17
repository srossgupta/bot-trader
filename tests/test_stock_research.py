import datetime as dt
import json
import os
import shutil
import tempfile
import unittest

from stock_research import history, schema, self_correction
from stock_research import trading_calendar as cal

RUN_DATE = "2026-06-17"        # a Wednesday
RESOLVE_DATE = "2026-06-23"    # RUN_DATE + 3 trading days (Fri 6/19 is Juneteenth)


def _pick(ticker="MU", **overrides):
    pick = {
        "ticker": ticker,
        "company": "Micron Technology",
        "direction": "UP",
        "confidence": 85,
        "sector": "Semiconductors",
        "catalyst": "HBM sold out",
        "signals_hit": ["forum_sentiment", "fundamental_catalyst"],
        "price_at_pick": 100.0,
        "price_source": "verified_close",
        "price_asof": RUN_DATE,
        "benchmark_at_pick": 600.0,
        "run_up_10d_pct": 0.05,
    }
    pick.update(overrides)
    return pick


class TradingCalendarTests(unittest.TestCase):
    def test_weekends_are_not_trading_days(self):
        self.assertFalse(cal.is_trading_day("2026-08-15"))  # Saturday
        self.assertFalse(cal.is_trading_day("2026-08-16"))  # Sunday
        self.assertTrue(cal.is_trading_day("2026-08-17"))   # Monday
        self.assertEqual(cal.closed_reason("2026-08-16"), "Sunday")

    def test_fixed_and_floating_holidays(self):
        self.assertEqual(cal.holiday_name("2026-01-01"), "New Year's Day")
        self.assertEqual(cal.holiday_name("2026-11-26"), "Thanksgiving Day")
        self.assertEqual(cal.holiday_name("2026-04-03"), "Good Friday")
        self.assertEqual(cal.holiday_name("2026-05-25"), "Memorial Day")

    def test_saturday_holiday_observed_on_friday(self):
        # July 4 2026 falls on a Saturday; the market closes Friday July 3.
        self.assertEqual(cal.holiday_name("2026-07-03"), "Independence Day")
        self.assertFalse(cal.is_trading_day("2026-07-03"))

    def test_add_trading_days_skips_weekends_and_holidays(self):
        # Friday + 1 trading day is Monday.
        self.assertEqual(cal.add_trading_days("2026-08-14", 1), dt.date(2026, 8, 17))
        # Wednesday + 3 trading days lands the following Tuesday, skipping Juneteenth.
        self.assertEqual(cal.add_trading_days(RUN_DATE, 3), dt.date(2026, 6, 23))
        # Thanksgiving week: Tue + 3 skips Thursday's closure.
        self.assertEqual(cal.add_trading_days("2026-11-24", 3), dt.date(2026, 11, 30))

    def test_add_trading_days_is_reversible(self):
        forward = cal.add_trading_days(RUN_DATE, 5)
        self.assertEqual(cal.add_trading_days(forward, -5), dt.date(2026, 6, 17))

    def test_trading_days_between(self):
        self.assertEqual(cal.trading_days_between(RUN_DATE, RESOLVE_DATE), 3)
        self.assertEqual(cal.trading_days_between(RESOLVE_DATE, RUN_DATE), 0)


class SchemaValidationTests(unittest.TestCase):
    def test_valid_pick_passes(self):
        self.assertEqual(schema.validate_pick(_pick()), [])

    def test_estimated_price_is_rejected(self):
        errors = schema.validate_pick(_pick(price_source="estimated"))
        self.assertTrue(any("verified" in e for e in errors))

    def test_missing_benchmark_price_is_rejected(self):
        errors = schema.validate_pick(_pick(benchmark_at_pick=None))
        self.assertTrue(any("benchmark_at_pick" in e for e in errors))

    def test_confidence_above_cap_is_rejected(self):
        errors = schema.validate_pick(_pick(confidence=100))
        self.assertTrue(any("exceeds the cap" in e for e in errors))
        self.assertEqual(schema.validate_pick(_pick(confidence=90)), [])

    def test_confidence_below_publish_floor_is_rejected(self):
        errors = schema.validate_pick(_pick(confidence=55))
        self.assertTrue(any("publish floor" in e for e in errors))

    def test_unknown_signal_is_rejected(self):
        errors = schema.validate_pick(_pick(signals_hit=["vibes"]))
        self.assertTrue(any("unknown signals" in e for e in errors))

    def test_non_trading_run_date_is_rejected(self):
        self.assertTrue(any("not a trading day"
                            in e for e in schema.validate_run_date("2026-08-16")))
        self.assertEqual(schema.validate_run_date(RUN_DATE), [])

    def test_sector_buckets_collapse_free_text(self):
        self.assertEqual(schema.sector_bucket("Semiconductors/AI Infrastructure"), "AI/Semis/Tech")
        self.assertEqual(schema.sector_bucket("AI Cloud Infrastructure"), "AI/Semis/Tech")
        self.assertEqual(schema.sector_bucket("Aerospace/eVTOL/Defense"), "Aerospace/Defense")
        self.assertEqual(schema.sector_bucket("Pharmaceuticals/GLP-1"), "Healthcare/Biotech")
        self.assertEqual(schema.sector_bucket("Widgets"), "Other")

    def test_chase_penalty_fires_on_big_run_up(self):
        self.assertEqual(schema.chase_penalty(_pick(run_up_10d_pct=0.30)), schema.CHASE_PENALTY)
        self.assertEqual(schema.chase_penalty(_pick(run_up_10d_pct=0.05)), 0)
        self.assertEqual(schema.chase_penalty(_pick(run_up_10d_pct=None)), 0)


class GradingTests(unittest.TestCase):
    def test_beating_the_benchmark_wins(self):
        graded = schema.grade("UP", 100, 110, 600, 600)  # +10% vs flat QQQ
        self.assertEqual(graded["outcome"], "WIN")
        self.assertAlmostEqual(graded["excess_vs_benchmark"], 0.10)

    def test_up_move_that_trails_the_benchmark_loses(self):
        # +3% while QQQ does +8% is a losing pick, even though it went up.
        graded = schema.grade("UP", 100, 103, 600, 648)
        self.assertEqual(graded["outcome"], "LOSS")
        self.assertTrue(graded["raw_direction_correct"])

    def test_tiny_move_is_flat_not_a_win(self):
        # The old rubric called +0.03% a WIN; a 2% threshold does not.
        graded = schema.grade("UP", 100, 100.03, 600, 600)
        self.assertEqual(graded["outcome"], "FLAT")

    def test_down_pick_wins_on_underperformance(self):
        graded = schema.grade("DOWN", 100, 95, 600, 600)
        self.assertEqual(graded["outcome"], "WIN")
        graded = schema.grade("DOWN", 100, 105, 600, 600)
        self.assertEqual(graded["outcome"], "LOSS")

    def test_down_pick_can_win_while_rising(self):
        # -1% relative underperformance is not enough; -5% is.
        graded = schema.grade("DOWN", 100, 102, 600, 648)  # +2% vs QQQ +8%
        self.assertEqual(graded["outcome"], "WIN")


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = history.RUNS_FILE
        history.RUNS_FILE = os.path.join(self.tmp, "runs.jsonl")

    def tearDown(self):
        history.RUNS_FILE = self._orig
        shutil.rmtree(self.tmp)

    def _save(self, *picks, run_date=RUN_DATE):
        return history.save_run({"run_date": run_date, "picks": list(picks) or [_pick()]})

    def test_save_run_derives_horizon_and_bucket(self):
        result = self._save()
        self.assertEqual(result["picks"], 1)
        pick = history.load_all_runs()[0]["picks"][0]
        self.assertEqual(pick["resolve_on"], RESOLVE_DATE)
        self.assertEqual(pick["horizon_trading_days"], 3)
        self.assertEqual(pick["sector_bucket"], "AI/Semis/Tech")
        self.assertFalse(pick["resolved"])

    def test_save_run_rejects_whole_run_on_one_bad_pick(self):
        with self.assertRaises(history.LedgerError) as ctx:
            self._save(_pick("MU"), _pick("SNDK", price_source="estimated"))
        self.assertIn("SNDK", str(ctx.exception))
        self.assertEqual(history.load_all_runs(), [])

    def test_save_run_rejects_duplicate_tickers(self):
        with self.assertRaises(history.LedgerError):
            self._save(_pick("MU"), _pick("MU"))

    def test_save_run_rejects_non_trading_date(self):
        with self.assertRaises(history.LedgerError):
            self._save(run_date="2026-06-20")  # Saturday

    def test_resolve_grades_once_and_refuses_to_regrade(self):
        self._save()
        result = history.resolve(RUN_DATE, "MU", 112.0, 606.0, as_of=RESOLVE_DATE)
        self.assertEqual(result["outcome"], "WIN")

        with self.assertRaises(history.LedgerError) as ctx:
            history.resolve(RUN_DATE, "MU", 130.0, 606.0, as_of=RESOLVE_DATE)
        self.assertIn("already resolved", str(ctx.exception))

        pick = history.load_all_runs()[0]["picks"][0]
        self.assertEqual(pick["resolution_price"], 112.0)  # unchanged by the retry
        self.assertTrue(pick["resolved"])

    def test_resolve_refuses_inside_the_horizon(self):
        self._save()
        with self.assertRaises(history.LedgerError) as ctx:
            history.resolve(RUN_DATE, "MU", 112.0, 606.0, as_of="2026-06-18")
        self.assertIn("inside the horizon", str(ctx.exception))

    def test_resolve_rejects_unknown_pick(self):
        self._save()
        with self.assertRaises(history.LedgerError):
            history.resolve(RUN_DATE, "NVDA", 112.0, 606.0, as_of=RESOLVE_DATE)

    def test_due_lists_only_matured_unresolved_picks(self):
        self._save()
        self.assertEqual(history.due_for_resolution("2026-06-18"), [])
        due = history.due_for_resolution(RESOLVE_DATE)
        self.assertEqual([d["ticker"] for d in due], ["MU"])
        self.assertEqual(due[0]["benchmark_at_pick"], 600.0)

        history.resolve(RUN_DATE, "MU", 112.0, 606.0, as_of=RESOLVE_DATE)
        self.assertEqual(history.due_for_resolution(RESOLVE_DATE), [])

    def test_record_next_open_measures_slippage_once(self):
        self._save()
        result = history.record_next_open(RUN_DATE, "MU", 103.0)
        self.assertAlmostEqual(result["slippage_pct"], 0.03)
        self.assertEqual(result["next_open_date"], "2026-06-18")
        with self.assertRaises(history.LedgerError):
            history.record_next_open(RUN_DATE, "MU", 104.0)

    def test_next_open_slippage_is_signed_against_the_position(self):
        self._save(_pick("MU", direction="DOWN"))
        result = history.record_next_open(RUN_DATE, "MU", 97.0)
        self.assertAlmostEqual(result["slippage_pct"], 0.03)

    def test_resaving_a_run_with_resolved_picks_is_refused(self):
        self._save()
        history.resolve(RUN_DATE, "MU", 112.0, 606.0, as_of=RESOLVE_DATE)
        with self.assertRaises(history.LedgerError) as ctx:
            self._save(_pick("NVDA"))
        self.assertIn("append-only", str(ctx.exception))

    def test_migrate_marks_legacy_picks_and_keeps_them_separate(self):
        legacy = {"run_date": "2026-06-10", "picks": [
            {"ticker": "OLD", "direction": "UP", "confidence": 100,
             "sector": "Semiconductors", "price_at_pick": 10.0,
             "price_later": 11.0, "outcome": "WIN", "signals_hit": ["technical"]},
            {"ticker": "OPEN", "direction": "UP", "confidence": 95,
             "sector": "Drone/Defense", "price_at_pick": 5.0, "outcome": None,
             "signals_hit": ["technical"]},
        ]}
        with open(history.RUNS_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps(legacy) + "\n")

        result = history.migrate()
        self.assertEqual(result, {"runs_stamped": 1, "legacy_graded_picks": 1,
                                  "legacy_open_picks": 1})
        old, open_pick = history.load_all_runs()[0]["picks"]
        self.assertEqual(old["grading"], "legacy_raw_direction")
        self.assertTrue(old["resolved"])
        self.assertEqual(open_pick["sector_bucket"], "Aerospace/Defense")

        # A legacy pick has no benchmark anchor, so it cannot be graded.
        with self.assertRaises(history.LedgerError) as ctx:
            history.resolve("2026-06-10", "OPEN", 6.0, 606.0, as_of="2026-06-22")
        self.assertIn("legacy", str(ctx.exception))

    def test_backfilled_benchmark_makes_a_legacy_pick_gradable(self):
        legacy = {"run_date": RUN_DATE, "picks": [
            {"ticker": "OPEN", "direction": "UP", "confidence": 85,
             "sector": "Semiconductors", "price_at_pick": 100.0, "outcome": None,
             "signals_hit": ["technical"]},
        ]}
        with open(history.RUNS_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps(legacy) + "\n")
        history.migrate()

        history.set_benchmark_entry(RUN_DATE, "OPEN", 600.0)
        result = history.resolve(RUN_DATE, "OPEN", 110.0, 600.0, as_of=RESOLVE_DATE)
        self.assertEqual(result["outcome"], "WIN")


class SelfCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = history.RUNS_FILE
        history.RUNS_FILE = os.path.join(self.tmp, "runs.jsonl")

    def tearDown(self):
        history.RUNS_FILE = self._orig
        shutil.rmtree(self.tmp)

    def _seed(self, n_picks, win_every=2, confidence=85):
        """Save one run of n_picks and resolve them with a known win pattern."""
        picks = [_pick(f"T{i}", confidence=confidence) for i in range(n_picks)]
        history.save_run({"run_date": RUN_DATE, "picks": picks})
        for i in range(n_picks):
            # WIN = +10% vs flat benchmark; LOSS = -10%.
            price = 110.0 if i % win_every == 0 else 90.0
            history.resolve(RUN_DATE, f"T{i}", price, 600.0, as_of=RESOLVE_DATE)

    def test_small_sample_does_not_move_the_rubric(self):
        self._seed(9, win_every=9)  # 1/9 wins — terrible, but only nine picks
        report = self_correction.compute_adjustments()
        self.assertFalse(report["sample_sufficient_for_rubric_change"])
        self.assertEqual(report["sector_penalties"], {})
        self.assertEqual(report["signal_penalties"], {})
        self.assertTrue(any("Sample too small" in n for n in report["notes"]))

    def test_large_sample_earns_penalties(self):
        self._seed(40, win_every=10)  # 4/40 wins
        report = self_correction.compute_adjustments()
        self.assertTrue(report["sample_sufficient_for_rubric_change"])
        self.assertEqual(report["sector_penalties"]["AI/Semis/Tech"], -10)
        self.assertIn("forum_sentiment", report["signal_penalties"])
        self.assertTrue(report["overconfidence_warning"])

    def test_calibration_scores_confidence(self):
        self._seed(40, win_every=2, confidence=90)  # forecast 90%, realized 50%
        cal_report = self_correction.compute_adjustments()["calibration"]
        self.assertEqual(cal_report["picks_scored"], 40)
        self.assertAlmostEqual(cal_report["mean_confidence"], 0.9)
        self.assertAlmostEqual(cal_report["realized_win_rate"], 0.5)
        self.assertGreater(cal_report["brier"], cal_report["baseline_brier"])
        self.assertLess(cal_report["skill_vs_base_rate"], 0)  # worse than the base rate
        band = next(b for b in cal_report["reliability"] if b["confidence_band"] == "80-90")
        self.assertEqual(band["n"], 40)

    def test_legacy_outcomes_stay_out_of_calibration(self):
        legacy = {"run_date": "2026-06-10", "picks": [
            {"ticker": "OLD", "direction": "UP", "confidence": 100,
             "sector": "Semiconductors", "price_at_pick": 10.0,
             "price_later": 10.003, "outcome": "WIN", "signals_hit": ["technical"]},
        ]}
        with open(history.RUNS_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps(legacy) + "\n")
        history.migrate()

        report = self_correction.compute_adjustments()
        self.assertEqual(report["resolved_benchmark_relative"], 0)
        self.assertEqual(report["resolved_legacy_raw"], 1)
        self.assertEqual(report["legacy_raw_win_rate"], 1.0)
        self.assertEqual(report["calibration"]["picks_scored"], 0)

    def test_concentration_is_flagged(self):
        picks = [_pick("A"), _pick("B"),
                 _pick("C", sector="Aerospace/Defense"),
                 _pick("D", sector="Pharmaceuticals")]
        history.save_run({"run_date": RUN_DATE, "picks": picks})
        conc = self_correction.compute_adjustments()["concentration_window"]
        self.assertEqual(conc["top_bucket"], "AI/Semis/Tech")
        self.assertEqual(conc["top_share"], 0.5)
        self.assertTrue(conc["flag"])

    def test_slippage_is_reported(self):
        history.save_run({"run_date": RUN_DATE, "picks": [_pick("A"), _pick("B")]})
        history.record_next_open(RUN_DATE, "A", 103.0)
        history.record_next_open(RUN_DATE, "B", 101.0)
        slip = self_correction.compute_adjustments()["slippage"]
        self.assertEqual(slip["picks_with_next_open"], 2)
        self.assertAlmostEqual(slip["mean_slippage_pct"], 0.02)


if __name__ == "__main__":
    unittest.main()
