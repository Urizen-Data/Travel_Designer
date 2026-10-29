"""Проверки словаря регионов (region_key)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.transform.regions import ALIASES, build_region_dictionary, region_key


class TestRegionKey(unittest.TestCase):
    def test_alias_kemerovo(self):
        self.assertEqual(region_key("Кемеровская область - Кузбасс"), "Кемеровская область")
        self.assertEqual(region_key("Кемеровская область"), "Кемеровская область")

    def test_alias_north_ossetia(self):
        canonical = "Республика Северная Осетия — Алания"
        self.assertEqual(region_key("Республика Северная Осетия — Алания"), canonical)
        self.assertEqual(region_key("Республика Северная Осетия-Алания"), canonical)
        self.assertEqual(region_key("Республика Северная Осетия - Алания"), canonical)

    def test_normalization_whitespace_and_dash(self):
        self.assertEqual(region_key("  Иркутская   область  "), "Иркутская область")
        self.assertEqual(region_key("Республика Алтай"), "Республика Алтай")

    def test_short_republic_forms(self):
        self.assertEqual(region_key("Карачаево-Черкесия"), "Карачаево-Черкесская Республика")
        self.assertEqual(region_key("Кабардино-Балкария"), "Кабардино-Балкарская Республика")
        self.assertEqual(region_key("Башкортостан"), "Республика Башкортостан")
        self.assertEqual(region_key("Хакасия"), "Республика Хакасия")

    def test_dictionary_has_20_unique_regions(self):
        regions = build_region_dictionary()["regions"]
        self.assertEqual(len(regions), 20)
        keys = [r["region_key"] for r in regions]
        self.assertEqual(len(keys), len(set(keys)), "region_key должен быть уникальным")

    def test_all_32_resorts_mapped(self):
        regions = build_region_dictionary()["regions"]
        total = sum(r["resort_count"] for r in regions)
        self.assertEqual(total, 32, "все 32 курорта должны быть приписаны к региону")

    def test_every_region_found_in_rosstat(self):
        regions = build_region_dictionary()["regions"]
        for r in regions:
            self.assertTrue(r["rosstat_names"], f"{r['region_key']} не найден в Росстате")


if __name__ == "__main__":
    unittest.main()
