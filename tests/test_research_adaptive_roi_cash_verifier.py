#!/usr/bin/env python3
"""Tests use synthetic fixtures ONLY. Never interpret their ROI as JRA evidence."""
import datetime as dt
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "cash_verifier", ROOT / "scripts" / "research-adaptive-roi-cash-verifier.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def bet(day, race, strategy, *, venue="東京", window=90):
    numbers = ("1", "1-2") if strategy == "A" else ("3", "3-4")
    return {
        "raceDate": day, "venue": venue, "raceId": f"{day}-{venue}-{race}",
        "strategy": strategy, "windowDays": window,
        "startTimeJst": "15:00:00",
        "modelTrainedThrough": (dt.date.fromisoformat(day) - dt.timedelta(days=1)).isoformat(),
        "lockedAt": day + "T14:40:00+09:00",
        "bets": [
            {"betType": typ, "combination": combo, "stakeYen": 100,
             "oddsSource": "JRA", "oddsCapturedAt": day + "T14:38:00+09:00"}
            for typ, combo in zip(("単勝", "ワイド"), numbers)
        ],
    }


def payout(day, race, *, a=True, venue="東京"):
    return {"raceDate": day, "venue": venue, "raceId": f"{day}-{venue}-{race}",
            "payoutSource": "JRA", "complete": True,
            "payouts": [{"betType": "単勝", "combination": "1" if a else "3",
                         "payoutYenPer100": 500}],
            "refunds": []}


class VerifyCash(unittest.TestCase):
    def test_cash_comes_from_independent_official_payout(self):
        day = "2025-01-01"
        historical = m.reconcile([bet(day, 1, "A"), bet(day, 1, "B")],
                                 [payout(day, 1)])
        self.assertEqual([r["returnYen"] for r in historical], [500, 0])
        self.assertEqual([r["stakeYen"] for r in historical], [200, 200])

    def test_reject_late_predictions_and_final_odds(self):
        d = "2025-01-01"
        r = bet(d, 1, "A")
        r["bets"][0]["oddsCapturedAt"] = d + "T14:55:00+09:00"
        with self.assertRaisesRegex(ValueError, "POST_T15_ODDS"):
            m.validate_candidate(r, settled=False)
        r = bet(d, 1, "A")
        r["modelTrainedThrough"] = d
        with self.assertRaisesRegex(ValueError, "POST_RACE_MODEL_TRAINING"):
            m.validate_candidate(r, settled=False)
        r = bet(d, 1, "A")
        r["bets"][0]["returnYen"] = 100
        with self.assertRaisesRegex(ValueError, "POST_RESULT_FIELDS"):
            m.validate_candidate(r, settled=False)

    def test_reject_missing_or_unverified_jra_payout(self):
        d = "2025-01-01"
        with self.assertRaisesRegex(ValueError, "MISSING_OFFICIAL_PAYOUT"):
            m.reconcile([bet(d, 1, "A")], [])
        bad = payout(d, 1)
        bad["payoutSource"] = "synthetic"
        with self.assertRaisesRegex(ValueError, "UNVERIFIED"):
            m.reconcile([bet(d, 1, "A")], [bad])

    def test_future_payout_cannot_change_past_live_choice(self):
        start = dt.date(2025, 1, 1)
        historical, pay = [], []
        for n in range(30):
            day = (start + dt.timedelta(days=n)).isoformat()
            for race in range(3):
                historical.extend([bet(day, race, "A"), bet(day, race, "B")])
                pay.append(payout(day, race, a=(n != 29)))
        settled = m.reconcile(historical, pay)
        target = (start + dt.timedelta(days=27)).isoformat()
        live = [bet(target, i, strategy) for i in range(3) for strategy in ("A", "B")]
        before = m.live_select(settled, live, min_bets=10, min_days=5)
        changed = [dict(r) for r in pay]
        for r in changed:
            if r["raceDate"] == (start + dt.timedelta(days=29)).isoformat():
                r["payouts"] = [{"betType": "単勝", "combination": "3",
                                 "payoutYenPer100": 50000}]
        after = m.live_select(m.reconcile(historical, changed), live, min_bets=10, min_days=5)
        self.assertEqual([(r["strategy"], r["windowDays"]) for r in before],
                         [(r["strategy"], r["windowDays"]) for r in after])
        self.assertEqual(before[0]["strategy"], "A")

    def test_refunds_are_reconstructed(self):
        d = "2025-01-01"
        p = payout(d, 1)
        p["refunds"] = [{"betType": "ワイド", "combination": "2-1"}]
        output = m.reconcile([bet(d, 1, "A")], [p])
        self.assertEqual(output[0]["returnYen"], 600)

    def test_refund_is_not_hit_and_cannot_fake_roi200(self):
        d = "2025-01-01"
        p = payout(d, 1)
        p["payouts"] = []
        p["refunds"] = [
            {"betType": "単勝", "combination": "1"},
            {"betType": "ワイド", "combination": "1-2"},
        ]
        row = m.reconcile([bet(d, 1, "A")], [p])[0]
        self.assertEqual(row["returnYen"], 200)
        self.assertFalse(row["hitRace"])
        self.assertEqual(row["maxWinningTicketReturn"], 0)
        normalized = [{**row, "day": dt.date.fromisoformat(d),
                       "stake": row["stakeYen"], "paid": row["returnYen"]}]
        stats = m.CORE.stats(normalized)
        self.assertEqual(stats["hitPct"], 0)

    def test_lagged_cutoff_requires_old_prediction_model(self):
        d = "2025-12-31"
        row = bet(d, 1, "A")
        row["lagDays"] = 365
        with self.assertRaisesRegex(ValueError, "POST_RACE_MODEL_TRAINING"):
            m.validate_candidate(row, settled=False)
        row["modelTrainedThrough"] = "2024-12-30"
        self.assertEqual(m.validate_candidate(row, settled=False), 200)

    def test_incomplete_strategy_unselectable(self):
        d = "2025-01-01"
        rows = [bet(d, i, "A") for i in range(3)] + [bet(d, 0, "B")]
        result = m.live_select([], rows, min_bets=1, min_days=1)
        self.assertEqual(result[0]["status"], "NO_VERIFIED_MODEL")


if __name__ == "__main__":
    unittest.main()
