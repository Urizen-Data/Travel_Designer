"""Проверки аналитической витрины ranking_insights."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analytics.ranking_insights import (
    build_component_rows,
    build_reason_rows,
    build_stability_rows,
    load_presets,
    load_scores,
)


class TestRankingInsights(unittest.TestCase):
    def setUp(self):
        self.scores = load_scores()
        self.presets = load_presets()
        self.stability = build_stability_rows(self.scores)
        self.components = build_component_rows(self.scores)

    def test_192_rows_6_per_resort(self):
        self.assertEqual(len(self.stability), 32 * 6)
        keys = {(r["resort_id"], r["preset_id"]) for r in self.stability}
        self.assertEqual(len(keys), 32 * 6)
        from collections import Counter
        cnt = Counter(r["resort_id"] for r in self.stability)
        self.assertEqual(set(cnt.values()), {6})

    def test_columns_are_exactly_11(self):
        self.assertEqual(len(self.stability[0]), 11)

    def test_name_ru_region_not_null(self):
        for row in self.stability:
            self.assertIsNotNone(row["name_ru"], row)
            self.assertNotEqual(row["name_ru"], "", row)
            self.assertIsNotNone(row["region"], row)
            self.assertNotEqual(row["region"], "", row)

    def test_name_ru_consistent_per_resort(self):
        by_resort = {}
        for row in self.stability:
            by_resort.setdefault(row["resort_id"], set()).add(row["name_ru"])
        for rid, names in by_resort.items():
            self.assertEqual(len(names), 1, f"{rid}: name_ru различается: {names}")

    def test_base_local_score_matches_old_formula(self):
        from src.analytics.ranking_insights import component_score
        base = {r["resort_id"]: r["local_score"] for r in self.stability if r["preset_id"] == "base"}
        for r in self.scores:
            rid = r["resort_id"]
            old_local = (float(r["popularity_score"]) - component_score(r, "regional") * 0.40) / 0.60
            self.assertAlmostEqual(base[rid], round(old_local, 2), delta=0.02, msg=rid)

    def test_local_rank_fields_valid(self):
        for row in self.stability:
            self.assertTrue(0.0 <= row["local_score"] <= 100.0, row)
            self.assertTrue(1 <= row["local_rank"] <= 32, row)
            self.assertTrue(1 <= row["median_rank"] <= 32, row)
            self.assertTrue(1 <= row["rank_p5"] <= 32, row)
            self.assertTrue(1 <= row["rank_p95"] <= 32, row)
            self.assertTrue(row["rank_p5"] <= row["median_rank"] <= row["rank_p95"], row)
            self.assertTrue(0.0 <= row["top10_frequency"] <= 1.0, row)

    def test_local_score_differs_by_preset(self):
        by_resort = {}
        for row in self.stability:
            by_resort.setdefault(row["resort_id"], {})[row["preset_id"]] = row["local_score"]
        for rid, scores in by_resort.items():
            self.assertEqual(len(scores), 6, rid)
            self.assertGreater(len(set(scores.values())), 1, f"{rid}: local_score не различается по пресетам")

    def test_determinism(self):
        again = build_stability_rows(self.scores)
        keys = ["median_rank", "rank_p5", "rank_p95", "top10_frequency", "local_score", "local_rank"]
        self.assertEqual(
            [(r["resort_id"], r["preset_id"]) for r in self.stability],
            [(r["resort_id"], r["preset_id"]) for r in again],
        )
        for a, b in zip(self.stability, again):
            for key in keys:
                self.assertEqual(a[key], b[key], f"{a['resort_id']}.{a['preset_id']}.{key}")

    def test_components_long_format_has_160_rows(self):
        self.assertEqual(len(self.components), 32 * 5)
        seen = {(r["resort_id"], r["component"]) for r in self.components}
        self.assertEqual(len(seen), 32 * 5)

    def test_reasons_32_unique(self):
        reasons = build_reason_rows(self.scores)
        self.assertEqual(len(reasons), 32)
        self.assertEqual(len({r["resort_id"] for r in reasons}), 32)

    def test_reason_types_and_text_valid(self):
        reasons = build_reason_rows(self.scores)
        valid_types = {"strength", "caveat", "tradeoff"}
        for row in reasons:
            for reason in row["reasons"]:
                self.assertIn(reason["type"], valid_types, row["resort_id"])
                self.assertTrue(reason["code"], row["resort_id"])
                self.assertTrue(reason["text"], row["resort_id"])

    def test_no_price_resorts_have_price_caveat(self):
        reasons = build_reason_rows(self.scores)
        no_price = {r["resort_id"] for r in self.scores if r.get("adult_skipass_avg_rub") is None}
        for row in reasons:
            if row["resort_id"] in no_price:
                codes = {r["code"] for r in row["reasons"]}
                self.assertIn("no_price", codes, row["resort_id"])

if __name__ == "__main__":
    unittest.main()
