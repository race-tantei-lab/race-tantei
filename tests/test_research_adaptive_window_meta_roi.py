#!/usr/bin/env python3
"""Regression tests for research-only adaptive-window ROI selection."""
import datetime as dt
import importlib.util
import tempfile
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("adaptive", ROOT / "scripts" / "research-adaptive-window-meta-roi.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def row(day, venue, race, strategy, paid, window=365):
    return {"raceDate": day, "venue": venue, "raceId": f"{day}-{venue}-{race}",
            "strategy": strategy, "windowDays": window, "stakeYen": 100,
            "returnYen": paid, "startTimeJst": "15:00:00",
            "lockedAt": day + "T14:40:00+09:00"}


class TestAdaptive(unittest.TestCase):
    def test_future_result_cannot_change_past_selection(self):
        data = []
        start = dt.date(2025, 1, 1)
        for i in range(28):
            day = (start + dt.timedelta(days=i)).isoformat()
            for race in range(3):
                data += [row(day, "東京", race, "A", 250),
                         row(day, "東京", race, "B", 0)]
        before = m.evaluate(m.load_rows(self.write(data)), 6, 2)
        changed = [dict(x) for x in data]
        for x in changed:
            if x["raceDate"] == changed[-1]["raceDate"]:
                x["returnYen"] = 0 if x["strategy"] == "A" else 10000
        after = m.evaluate(m.load_rows(self.write(changed)), 6, 2)
        self.assertEqual([(d["date"], d["strategy"]) for d in before["decisions"]],
                         [(d["date"], d["strategy"]) for d in after["decisions"]])

    def test_late_lock_rejected(self):
        with self.assertRaises(ValueError):
            m.load_rows(self.write([{**row("2025-01-01", "東京", 1, "A", 0),
                                     "lockedAt": "2025-01-01T14:50:00+09:00"}]))

    def test_incomplete_candidate_not_selected(self):
        day = "2025-01-01"
        rows = [row(day, "東京", i, "A", 0) for i in range(3)]
        rows.append(row(day, "東京", 0, "B", 10000))
        report = m.evaluate(m.load_rows(self.write(rows)), 1, 1)
        self.assertFalse(report["decisions"])

    def write(self, rows):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
        with f:
            for x in rows:
                f.write(json.dumps(x) + "\n")
        self.addCleanup(lambda: Path(f.name).unlink(missing_ok=True))
        return f.name


if __name__ == "__main__":
    unittest.main()
