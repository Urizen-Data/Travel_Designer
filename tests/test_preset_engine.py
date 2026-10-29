"""Проверки сценарных пресетов скоринга (перевзвешивание 5 компонентов)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.scoring.preset_engine import (
    COMPONENTS,
    build_preset_tables,
    load_config,
    validate_config,
)


class TestPresetEngine(unittest.TestCase):
    def setUp(self):
        self.preset_rows, self.component_rows = build_preset_tables()

    def test_weights_sum_100(self):
        for p in load_config()["presets"]:
            w = p["weights"]
            self.assertAlmostEqual(
                sum(float(w[c]) for c in COMPONENTS), 100.0, places=2, msg=p["preset_id"]
            )

    def test_six_presets(self):
        self.assertEqual(len(self.preset_rows), 6)

    def test_960_rows(self):
        self.assertEqual(len(self.component_rows), 6 * 32 * 5)

    def test_base_reproduces_popularity(self):
        for r in self.component_rows:
            if r["preset_id"] == "base" and r["component"] == "regional":
                self.assertAlmostEqual(
                    r["scenario_score"], r["base_score"], places=2, msg=r["resort_id"]
                )

    def test_contributions_sum_to_score(self):
        for rid in {r["resort_id"] for r in self.component_rows}:
            for preset in {r["preset_id"] for r in self.component_rows}:
                rows = [
                    r for r in self.component_rows
                    if r["resort_id"] == rid and r["preset_id"] == preset
                ]
                self.assertEqual(len(rows), 5, msg=f"{preset}/{rid}")
                contrib = sum(r["contribution"] for r in rows)
                self.assertAlmostEqual(contrib, rows[0]["scenario_score"], places=2, msg=f"{preset}/{rid}")

    def test_rank_1_to_32(self):
        for preset in {r["preset_id"] for r in self.component_rows}:
            ranks = sorted({r["scenario_rank"] for r in self.component_rows if r["preset_id"] == preset})
            self.assertEqual(ranks, list(range(1, 33)), msg=preset)

    def test_rank_change_consistency(self):
        for r in self.component_rows:
            if r["component"] == "regional":
                self.assertEqual(r["rank_change"], r["base_rank"] - r["scenario_rank"])


if __name__ == "__main__":
    unittest.main()
