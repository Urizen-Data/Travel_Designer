"""Проверки витрины atlas_catalog (материализация SQL-вьюх)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analytics.build_atlas_catalog import build_scenarios, build_wide  # noqa: E402
from src.common.mart_io import read_csv  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]

COMPONENTS = ("regional", "infrastructure", "winter", "accessibility", "price")


class TestBuildAtlasCatalog(unittest.TestCase):
    def setUp(self):
        self.wide = build_wide()
        self.rows = build_scenarios(self.wide)
        self.by_id: dict[str, list] = {}
        for r in self.rows:
            self.by_id.setdefault(r["scenario_id"], []).append(r)

    def test_wide_192_rows_81_cols(self):
        self.assertEqual(len(self.wide), 192)
        self.assertEqual(len(self.wide[0]), 81)

    def test_scenario_blocks_sizes(self):
        self.assertEqual(len(self.by_id["all_top"]), 192)
        regions = {r["region"] for r in self.wide}
        self.assertEqual(len(self.by_id["all_diversity"]), 6 * len(regions))
        member_ids = [k for k in self.by_id if k not in ("all_top", "all_diversity")]
        scenarios = read_csv(PROJECT_ROOT / "data" / "mart" / "catalog_scenarios.csv")
        expected = sum(int(s["n"]) for s in scenarios if s["strategy"] in ("top", "diversity"))
        self.assertEqual(sum(len(self.by_id[k]) for k in member_ids), expected)

    def test_all_diversity_picks_best_scenario_score(self):
        by_key: dict[tuple[str, str], list] = {}
        for r in self.wide:
            by_key.setdefault((r["preset_id"], r["region"]), []).append(r)
        div = {
            (r["preset_id"], r["region"]): r
            for r in self.rows if r["scenario_id"] == "all_diversity"
        }
        for key, candidates in by_key.items():
            best = max(c["scenario_score"] for c in candidates)
            self.assertEqual(div[key]["scenario_score"], best, key)

    def test_contributions_sum_to_scenario_score(self):
        for r in self.rows:
            total = sum(r[f"{c}_contribution"] for c in COMPONENTS)
            self.assertAlmostEqual(total, r["scenario_score"], delta=0.6,
                                   msg=f"{r['scenario_id']}/{r['resort_id']}")

    def test_has_observed_price_is_bool(self):
        for r in self.rows:
            self.assertIsInstance(r["has_observed_price"], bool)

    def test_member_meta_consistent(self):
        scenarios = {s["scenario_id"]: s for s in read_csv(PROJECT_ROOT / "data" / "mart" / "catalog_scenarios.csv")}
        for r in self.rows:
            if r["scenario_id"] in ("all_top", "all_diversity"):
                self.assertIsNone(r["n"])
                self.assertEqual(r["size_label"], "Все")
            else:
                s = scenarios[r["scenario_id"]]
                self.assertEqual(r["n"], int(s["n"]), r["scenario_id"])
                self.assertEqual(r["size_label"], str(s["n"]), r["scenario_id"])
                self.assertEqual(r["scenario_label"], s["scenario_label"], r["scenario_id"])
                self.assertEqual(r["strategy_name_ru"], s["strategy_name_ru"], r["scenario_id"])

    def test_wide_fields_present(self):
        row = self.wide[0]
        for field in ("scenario_score", "scenario_rank", "base_score", "base_rank",
                      "rank_change", "has_observed_price", "confidence_score",
                      "official_website_url", "skimap_url", "details_url",
                      "stability_median_rank", "local_score", "local_rank"):
            self.assertIn(field, row)
        for removed in ("median_rank", "rank_p5", "rank_p95", "top10_frequency"):
            self.assertNotIn(removed, row)

    def test_stability_fields_not_null(self):
        for r in self.rows:
            self.assertIsNotNone(r["stability_median_rank"], r["scenario_id"] + "/" + r["resort_id"])
            self.assertIsNotNone(r["local_score"])
            self.assertIsNotNone(r["local_rank"])


if __name__ == "__main__":
    unittest.main()
