"""Проверки разворота прогноза trip_conditions."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analytics.trip_conditions import VALID_CONDITIONS, build_daily_rows, load_forecast


class TestTripConditions(unittest.TestCase):
    def setUp(self):
        payload = load_forecast()
        self.rows = build_daily_rows(payload)

    def test_320_rows(self):
        self.assertEqual(len(self.rows), 32 * 10)

    def test_32_unique_resorts(self):
        self.assertEqual(len({r["resort_id"] for r in self.rows}), 32)

    def test_conditions_valid(self):
        for r in self.rows:
            self.assertIn(r["slope_condition"], VALID_CONDITIONS, r["resort_id"])

    def test_reason_and_limitations_present(self):
        for r in self.rows:
            self.assertTrue(r["condition_reason"], r["resort_id"])
            self.assertTrue(r["condition_limitations"], r["resort_id"])

    def test_ten_days_horizon(self):
        dates = {r["date"] for r in self.rows}
        self.assertEqual(len(dates), 10)


if __name__ == "__main__":
    unittest.main()
