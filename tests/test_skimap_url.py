"""Проверки генерации skimap_url из openskimap_sources."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.collect.fetch_skimap_ids import resolve_skimap, skimap_id_from_sources


class TestSkimapUrl(unittest.TestCase):
    def test_extract_id_from_sources(self):
        self.assertEqual(
            skimap_id_from_sources("openstreetmap:relation/6929820; skimap.org:2678"), "2678"
        )
        self.assertEqual(
            skimap_id_from_sources("openstreetmap:way/1266093626; skimap.org:1935"), "1935"
        )

    def test_first_of_multiple_skimap_ids(self):
        self.assertEqual(
            skimap_id_from_sources("openstreetmap:relation/6929818; skimap.org:1947; skimap.org:3091"),
            "1947",
        )

    def test_no_skimap_returns_none(self):
        self.assertIsNone(skimap_id_from_sources("openstreetmap:relation/6930862"))
        self.assertIsNone(skimap_id_from_sources(None))
        self.assertIsNone(skimap_id_from_sources(""))

    def test_resolve_skimap_specific(self):
        sid, url = resolve_skimap("Роза Хутор", "openstreetmap:relation/6929820; skimap.org:2678")
        self.assertEqual(sid, 2678)
        self.assertEqual(url, "https://skimap.org/skiareas/view/2678")

    def test_resolve_skimap_base_fallback(self):
        sid, url = resolve_skimap("Эльбрус", "openstreetmap:relation/6930862")
        self.assertIsNone(sid)
        self.assertEqual(url, "https://skimap.org")

    def test_resolve_skimap_known_id(self):
        sid, url = resolve_skimap("КолаСпортЛэнд", None)
        self.assertEqual(sid, 3081)
        self.assertEqual(url, "https://skimap.org/skiareas/view/3081")


if __name__ == "__main__":
    unittest.main()
