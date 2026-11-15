#!/usr/bin/env python3
"""Synthetic CASH fixtures. They are not evidence of JRA profitability."""
import datetime as dt
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "meta_method_discovery", ROOT / "scripts" / "research-adaptive-method-discovery.py")
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def fixture(start=dt.date(2025, 1, 1), days=80, winning_paid=900,
            holdout_paid=None, missing=False):
    rows = []
    for i in range(days):
        day = start + dt.timedelta(days=i)
        iso = day.isoformat()
        for race in range(2 if missing else 3):
            for strategy, window in (("A", 90), ("B", 180)):
                pay = winning_paid if strategy == "A" and race == 0 else 0
                if i >= 56 and holdout_paid is not None:
                    pay = holdout_paid if strategy == "A" and race == 0 else 0
                rows.append({
                    "raceDate": iso, "raceId": f"{iso}-tokyo-{race}",
                    "venue": "東京", "strategy": strategy, "windowDays": window,
                    "lagDays": 0, "stakeYen": 100, "returnYen": pay,
                    "hitRace": bool(pay), "maxWinningTicketReturn": pay,
                })
    return m.normalize(rows)


START = dt.date(2025, 1, 1)
VAL_START = START + dt.timedelta(days=31)
VAL_END = START + dt.timedelta(days=55)
HOLD_START = START + dt.timedelta(days=56)
HOLD_END = START + dt.timedelta(days=79)

METHODS = [
    m.Algorithm("trimmed_cash", "global", 100, 24),
    m.Algorithm("median_month", "adaptive", 300, 24),
]


class DiscoveryContractTests(unittest.TestCase):
    def test_only_genuinely_qualifying_method_becomes_model(self):
        result = m.discover(fixture(), VAL_START, VAL_END, HOLD_START,
                            HOLD_END, METHODS)
        self.assertEqual(result["methodsGenerated"], 2)
        self.assertEqual(result["forwardVerifiedCount"], 1)
        self.assertEqual(len(result["models"]), 1)
        mm = result["models"][0]
        self.assertGreaterEqual(mm["validation"]["cashRoiPct"], 200)
        self.assertGreaterEqual(mm["independentHoldout"]["minusLargestRaceCashRoiPct"], 200)
        self.assertGreaterEqual(mm["independentHoldout"]["hitRacePct"], 20)
        self.assertEqual(mm["minimumRacesPerVenueDay"], 3)
        self.assertFalse(mm["productionEligible"])

    def test_below200_not_listed_or_named(self):
        result = m.discover(fixture(winning_paid=450), VAL_START, VAL_END,
                            HOLD_START, HOLD_END, METHODS)
        self.assertEqual(result["validationQualifiedCount"], 0)
        self.assertEqual(result["forwardVerifiedCount"], 0)
        self.assertEqual(result["models"], [])
        self.assertNotIn("bestFailedModel", result)
        self.assertNotIn("rejectedModels", result)
        self.assertNotIn("overallRoi", result)

    def test_validation_pass_then_holdout_fails_no_model(self):
        result = m.discover(fixture(holdout_paid=0), VAL_START, VAL_END,
                            HOLD_START, HOLD_END, METHODS)
        self.assertGreater(result["validationQualifiedCount"], 0)
        self.assertEqual(result["forwardVerifiedCount"], 0)
        self.assertEqual(result["models"], [])

    def test_incomplete_venue_day_is_not_filtered_into_success(self):
        result = m.discover(fixture(missing=True), VAL_START, VAL_END,
                            HOLD_START, HOLD_END, METHODS)
        self.assertEqual(result["models"], [])

    def test_future_payout_never_changes_earlier_decisions(self):
        a = fixture()
        b = [dict(x) for x in a]
        after = HOLD_START + dt.timedelta(days=15)
        for row in b:
            if row["day"] > after and row["strategy"] == "A":
                row["paid"] = 0
                row["returnYen"] = 0
                row["hitRace"] = False
                row["maxWinningTicketReturn"] = 0
        x = m.replay(a, METHODS[0], HOLD_START, after)
        y = m.replay(b, METHODS[0], HOLD_START, after)
        self.assertEqual(x["selected"], y["selected"])
        self.assertEqual(x["money"], y["money"])

    def test_no_overlapping_tuning_or_holdout(self):
        with self.assertRaisesRegex(ValueError, "OVERLAPPING"):
            m.discover(fixture(), VAL_START, HOLD_START, HOLD_START,
                       HOLD_END, METHODS)

    def test_generate_multiple_meta_model_methods_not_single_static_rule(self):
        kinds = m.generate_methods()
        self.assertGreaterEqual(len(kinds), 48)
        self.assertGreaterEqual(len({x.objective for x in kinds}), 4)
        self.assertGreaterEqual(len({x.scope for x in kinds}), 3)


if __name__ == "__main__":
    unittest.main()
