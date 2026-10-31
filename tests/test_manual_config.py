"""Проверки единого ручного конфига resorts_manual.json."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.collect.manual_inputs import (  # noqa: E402
    append_resort,
    load_manual_prices,
    load_resorts_manual,
    next_resort_id,
    remove_resort,
    update_resort,
)
from src.collect.prices import run_parsers as rp  # noqa: E402
from src.transform import apply_coordinates as ac  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _resort(name: str, rid: str | None = None, **kw) -> dict:
    r = {
        "name_ru": name, "region": "Регион", "settlement": "", "lat": None,
        "lon": None, "official_website_url": None, "details_url": None,
        "skimap_url": None, "prices": [],
    }
    if rid:
        r["resort_id"] = rid
    r.update(kw)
    return r


class TestLoadResortsManual(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_resorts_manual(Path(d) / "nope.json"), [])

    def test_empty_resorts_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "resorts_manual.json"
            _write_json(p, {"resorts": []})
            self.assertEqual(load_resorts_manual(p), [])

    def test_valid_resorts_loaded(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "resorts_manual.json"
            _write_json(p, {"resorts": [_resort("Тест", "R001")]})
            loaded = load_resorts_manual(p)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["resort_id"], "R001")


class TestLoadManualPrices(unittest.TestCase):
    def test_flattens_prices(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "resorts_manual.json"
            _write_json(p, {"resorts": [
                _resort("А", "R001", prices=[{"month": None, "adult_price_min_rub": 100, "source_quality": "manual"}]),
                _resort("Б", "R002", prices=[{"month": "2026-01", "adult_price_min_rub": 200, "source_quality": "secondary"}]),
            ]})
            rows = load_manual_prices(p)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["resort_id"], "R001")
        self.assertEqual(rows[1]["resort_name"], "Б")

    def test_no_prices_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "resorts_manual.json"
            _write_json(p, {"resorts": [_resort("А", "R001")]})
            self.assertEqual(load_manual_prices(p), [])


class TestNextResortId(unittest.TestCase):
    def test_returns_next(self):
        self.assertEqual(next_resort_id([_resort("А", "R001"), _resort("Б", "R002")]), "R003")
        self.assertEqual(next_resort_id([_resort("А", "R032")]), "R033")

    def test_empty_returns_r001(self):
        self.assertEqual(next_resort_id([]), "R001")


class TestAppendResort(unittest.TestCase):
    def test_appends_with_auto_id(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "resorts_manual.json"
            _write_json(p, {"resorts": [_resort("А", "R001")]})
            rid = append_resort({"name_ru": "Б", "region": "Регион"}, p)
            self.assertEqual(rid, "R002")
            self.assertEqual(len(load_resorts_manual(p)), 2)

    def test_dedups_by_name(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "resorts_manual.json"
            _write_json(p, {"resorts": [_resort("Тест", "R001")]})
            rid = append_resort({"name_ru": "тест", "region": "Р2"}, p)
            self.assertEqual(rid, "R001")
            self.assertEqual(len(load_resorts_manual(p)), 1)


class TestUpdateRemoveResort(unittest.TestCase):
    def _file(self, d) -> Path:
        p = Path(d) / "resorts_manual.json"
        _write_json(p, {"resorts": [_resort("Тест", "R001", region="Р1")]})
        return p

    def test_update_by_id(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._file(d)
            self.assertTrue(update_resort("R001", {"official_website_url": "https://x.ru"}, p))
            self.assertEqual(load_resorts_manual(p)[0]["official_website_url"], "https://x.ru")

    def test_update_by_name(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._file(d)
            self.assertTrue(update_resort("тест", {"lat": 55.0, "lon": 37.0}, p))
            self.assertEqual(load_resorts_manual(p)[0]["lat"], 55.0)

    def test_update_unknown_returns_false(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._file(d)
            self.assertFalse(update_resort("нет такого", {"lat": 1}, p))

    def test_remove_by_id(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._file(d)
            removed = remove_resort("r001", p)
            self.assertEqual(removed["name_ru"], "Тест")
            self.assertEqual(load_resorts_manual(p), [])

    def test_remove_unknown_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._file(d)
            self.assertIsNone(remove_resort("нет такого", p))


class TestRunParsersBuildRows(unittest.TestCase):
    def _monthly(self):
        return {"resort_id": "R001", "resort_name": "Роза", "month": "2026-01",
                "adult_price_min_rub": 5000, "adult_price_max_rub": 6000,
                "child_price_min_rub": None, "child_price_max_rub": None,
                "tariff_product": "Ски-пасс", "coverage": None,
                "source_quality": "secondary", "source_url": None, "checked_at": "2026-09-14"}

    def _manual(self):
        return {"resort_id": "R001", "resort_name": "Роза", "month": None,
                "adult_price_min_rub": 4200, "adult_price_max_rub": 4200,
                "child_price_min_rub": None, "child_price_max_rub": None,
                "tariff_product": "Ски-пасс на 1 день", "coverage": None,
                "source_quality": "manual", "source_url": "x", "checked_at": None}

    def test_manual_overrides_monthly(self):
        with mock.patch.object(rp, "load_manual_prices", return_value=[self._monthly(), self._manual()]), \
             mock.patch.object(rp, "run_parsers", return_value={}):
            rows = rp.build_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["adult_price_min_rub"], 4200)
        self.assertEqual(rows[0]["source_quality"], "manual")

    def test_monthly_used_when_no_manual(self):
        with mock.patch.object(rp, "load_manual_prices", return_value=[self._monthly()]), \
             mock.patch.object(rp, "run_parsers", return_value={}):
            rows = rp.build_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["adult_price_min_rub"], 5000)


class TestApplyCoordinates(unittest.TestCase):
    def test_to_float(self):
        self.assertIsNone(ac._to_float(""))
        self.assertIsNone(ac._to_float(None))
        self.assertEqual(ac._to_float("55.5"), 55.5)

    def test_load_resorts_reads_manual(self):
        resort = _resort("Тест", "R001", region="Регион", settlement="Нас", lat=55.5, lon=37.7)
        with mock.patch.object(ac, "load_resorts_manual", return_value=[resort]):
            resorts = ac.load_resorts()
        self.assertEqual(resorts[0]["resort_id"], "R001")
        self.assertEqual(resorts[0]["settlement"], "Нас")
        self.assertEqual(resorts[0]["lat"], 55.5)
        self.assertEqual(resorts[0]["lon"], 37.7)


if __name__ == "__main__":
    unittest.main()

