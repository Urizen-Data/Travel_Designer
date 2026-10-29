"""Проверки рейтинга resort_scores."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.scoring.score_resorts import WEIGHTS, build_scores, build_weights_table


class TestResortScores(unittest.TestCase):
    def setUp(self):
        self.rows = build_scores()

    def test_weights_sum_100(self):
        self.assertAlmostEqual(sum(WEIGHTS.values()), 100.0, places=3)

    def test_32_unique_resorts(self):
        self.assertEqual(len(self.rows), 32)
        self.assertEqual(len({r["resort_id"] for r in self.rows}), 32)

    def test_scores_in_0_100(self):
        for r in self.rows:
            for k in WEIGHTS:
                v = r[k + "_score"]
                self.assertTrue(0.0 <= v <= 100.0, f"{r['resort_id']}.{k}_score={v}")
            self.assertTrue(0.0 <= r["popularity_score"] <= 100.0)
            self.assertTrue(0.0 <= r["confidence_score"] <= 100.0)

    def test_finite_and_rank(self):
        ranks = [r["rank"] for r in self.rows]
        self.assertEqual(ranks, list(range(1, 33)), "rank должен быть 1..32 без пропусков")
        for r in self.rows:
            self.assertTrue(math.isfinite(r["popularity_score"]))
            self.assertTrue(math.isfinite(r["confidence_score"]))

    def test_sorted_by_score_desc(self):
        scores = [r["popularity_score"] for r in self.rows]
        self.assertEqual(scores, sorted(scores, reverse=True))


class TestScoringWeightsTable(unittest.TestCase):
    def setUp(self):
        self.rows = build_weights_table()

    def test_13_indicator_rows(self):
        self.assertEqual(len(self.rows), 13)

    def test_indicator_weights_sum_100(self):
        self.assertAlmostEqual(sum(r["indicator_weight"] for r in self.rows), 100.0, places=3)

    def test_5_components_and_component_weights_sum_100(self):
        unique = {r["component"]: r["component_weight"] for r in self.rows}
        self.assertEqual(len(unique), 5)
        self.assertAlmostEqual(sum(unique.values()), 100.0, places=3)

    def test_component_subweights_match_component_weight(self):
        by_component = {}
        for r in self.rows:
            d = by_component.setdefault(r["component"], {"weight": r["component_weight"], "sub": 0.0})
            d["sub"] += r["indicator_weight"]
        for comp, d in by_component.items():
            self.assertAlmostEqual(d["sub"], d["weight"], places=3, msg=comp)

    def test_russian_names_present(self):
        for r in self.rows:
            self.assertTrue(r["component_name_ru"], r["component"])
            self.assertTrue(r["indicator_name_ru"], r["indicator"])


if __name__ == "__main__":
    unittest.main()
