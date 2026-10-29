"""Проверки сценариев стартового каталога (мультипресетные)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analytics.catalog_builder import (  # noqa: E402
    N_VALUES,
    STRATEGIES,
    build_scenarios,
    load_presets,
    load_scores_for_preset,
)
from src.common.mart_io import read_csv  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestCatalogBuilder(unittest.TestCase):
    def setUp(self):
        presets = load_presets()
        self.preset_ids = [p["preset_id"] for p in presets]
        self.preset_names = {p["preset_id"]: p["name_ru"] for p in presets}
        self.scenarios, self.members = build_scenarios(self.preset_ids, self.preset_names)

    def test_scenario_count_72(self):
        self.assertEqual(len(self.scenarios), len(self.preset_ids) * len(N_VALUES) * len(STRATEGIES))
        self.assertEqual(len(self.scenarios), 72)

    def test_members_match_n_unique(self):
        for row in self.scenarios:
            members = [m for m in self.members if m["scenario_id"] == row["scenario_id"]]
            self.assertEqual(len(members), row["n"], row["scenario_id"])
            self.assertEqual(len({m["resort_id"] for m in members}), row["n"], row["scenario_id"])

    def test_diversity_max_one_per_region(self):
        for row in self.scenarios:
            if row["strategy"] in ("diversity", "diversity_verified"):
                self.assertEqual(row["region_count"], row["n"], row["scenario_id"])

    def test_top_avg_not_less_than_diversity(self):
        by_key = {}
        for row in self.scenarios:
            by_key.setdefault((row["preset_id"], row["n"]), {})[row["strategy"]] = row["avg_index"]
        for (pid, n), avgs in by_key.items():
            self.assertGreaterEqual(avgs["top"], avgs["diversity"], f"{pid}/n={n}")

    def test_all_feasible(self):
        for row in self.scenarios:
            self.assertEqual(row["status"], "feasible", row["scenario_id"])

    def test_max_region_share_in_range(self):
        for row in self.scenarios:
            self.assertTrue(0.0 <= row["max_region_share"] <= 1.0, row["scenario_id"])

    def test_avg_index_vs_top_invariants(self):
        for row in self.scenarios:
            if row["strategy"] == "top":
                self.assertAlmostEqual(row["avg_index_vs_top"], 0.0, delta=0.02, msg=row["scenario_id"])
            else:
                self.assertLessEqual(row["avg_index_vs_top"], 0.02, row["scenario_id"])

    def test_presets_really_affect_composition(self):
        def composition(pid: str) -> set[str]:
            return {m["resort_id"] for m in self.members if m["scenario_id"] == f"{pid}_diversity_n10"}

        base = composition("base")
        snow = composition("snow")
        infra = composition("infra")
        self.assertNotEqual(base, snow, "snow должен менять состав diversity_n10")
        self.assertNotEqual(base, infra, "infra должен менять состав diversity_n10")

    def test_base_scenario_score_equals_popularity(self):
        scores = read_csv(PROJECT_ROOT / "data" / "mart" / "resort_scores.csv")
        popularity = {r["resort_id"]: float(r["popularity_score"]) for r in scores}
        base_scores = load_scores_for_preset("base")
        self.assertEqual(len(base_scores), 32)
        for r in base_scores:
            self.assertAlmostEqual(r["scenario_score"], popularity[r["resort_id"]], places=2, msg=r["resort_id"])


if __name__ == "__main__":
    unittest.main()

