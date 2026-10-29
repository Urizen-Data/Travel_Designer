"""Проверки разбора сложности/типов трасс из OSM."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.collect.recompute_resort_data import parse_piste_elements


def _el(ptype, difficulty=None):
    tags = {"piste:type": ptype}
    if difficulty:
        tags["piste:difficulty"] = difficulty
    return {"tags": tags}


class TestParsePisteElements(unittest.TestCase):
    def test_empty(self):
        r = parse_piste_elements([])
        self.assertEqual(r["piste_ways_total"], 0)
        self.assertEqual(r["piste_difficulty_unknown"], 0)
        self.assertIsNone(r["piste_difficulty_coverage"])

    def test_downhill_difficulty_breakdown(self):
        els = [
            _el("downhill", "easy"),
            _el("downhill", "easy"),
            _el("downhill", "intermediate"),
            _el("downhill", "novice"),
            _el("downhill"),  # без difficulty
        ]
        r = parse_piste_elements(els)
        self.assertEqual(r["piste_ways_total"], 5)
        self.assertEqual(r["piste_difficulty_easy"], 2)
        self.assertEqual(r["piste_difficulty_intermediate"], 1)
        self.assertEqual(r["piste_difficulty_novice"], 1)
        self.assertEqual(r["piste_difficulty_unknown"], 1)
        self.assertAlmostEqual(r["piste_difficulty_coverage"], 4 / 5)

    def test_difficulty_only_on_downhill(self):
        els = [
            _el("downhill", "advanced"),
            _el("nordic", "easy"),  # difficulty на nordic НЕ учитывается в сложности
            _el("skitour"),
            _el("sled"),
        ]
        r = parse_piste_elements(els)
        self.assertEqual(r["piste_ways_total"], 4)
        self.assertEqual(r["piste_difficulty_advanced"], 1)
        self.assertEqual(r["piste_difficulty_easy"], 0)
        self.assertEqual(r["piste_type_nordic"], 1)
        self.assertEqual(r["piste_type_skitour"], 1)
        self.assertEqual(r["piste_type_sled"], 1)

    def test_invariant_downhill_equals_sum(self):
        els = [
            _el("downhill", "easy"),
            _el("downhill", "expert"),
            _el("downhill"),
            _el("nordic"),
            _el("snow_park", "freeride"),
        ]
        r = parse_piste_elements(els)
        levels = ["novice", "easy", "intermediate", "advanced", "expert", "freeride", "extreme"]
        diff_sum = sum(r[f"piste_difficulty_{l}"] for l in levels)
        self.assertEqual(diff_sum + r["piste_difficulty_unknown"], 3)  # 3 downhill-way
        self.assertEqual(r["piste_type_snow_park"], 1)


if __name__ == "__main__":
    unittest.main()
