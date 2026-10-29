"""Проверки агрегации регионального спроса (Росстат)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.transform.regional_demand import build_region_metrics


class TestRegionalDemand(unittest.TestCase):
    def setUp(self):
        self.metrics = build_region_metrics()

    def test_20_unique_regions(self):
        self.assertEqual(len(self.metrics), 20)
        keys = [m["region_key"] for m in self.metrics]
        self.assertEqual(len(keys), len(set(keys)), "region_key должен быть уникальным")

    def test_no_missing_trips_2025(self):
        for m in self.metrics:
            self.assertIsNotNone(m["trips_2025"], m["region_key"])
            self.assertGreater(m["trips_2025"], 0)

    def test_positive_nights(self):
        for m in self.metrics:
            self.assertIsNotNone(m["nights_2025"], m["region_key"])
            self.assertGreater(m["nights_2025"], 0)

    def test_growth_and_stay_computed(self):
        for m in self.metrics:
            self.assertIsNotNone(m["trips_growth_2025"])
            self.assertIsNotNone(m["avg_stay_nights_2025"])
            self.assertGreater(m["avg_stay_nights_2025"], 0)

    def test_growth_formula(self):
        for m in self.metrics:
            expected = m["trips_2025"] / m["trips_2024"] - 1.0
            self.assertAlmostEqual(m["trips_growth_2025"], expected, places=8)

    def test_stay_formula(self):
        for m in self.metrics:
            expected = m["nights_2025"] / m["trips_2025"]
            self.assertAlmostEqual(m["avg_stay_nights_2025"], expected, places=8)


if __name__ == "__main__":
    unittest.main()
