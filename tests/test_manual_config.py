"""Проверки ручных конфигов (resorts_manual.json / prices_manual.json)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.collect.manual_inputs import (  # noqa: E402
    load_prices_manual,
    load_resorts_manual,
    merge_resorts_into_seed,
)
from src.collect.prices import run_parsers as rp  # noqa: E402
from src.transform import apply_coordinates as ac  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


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
            entry = {"name_ru": "Тест", "region": "Регион", "lat": 55.0, "lon": 37.0}
            _write_json(p, {"resorts": [entry]})
            self.assertEqual(load_resorts_manual(p), [entry])


class TestMergeResortsIntoSeed(unittest.TestCase):
    HEADER = "name_ru,region,settlement,lat,lon\n"

    def test_adds_new_resort(self):
        with tempfile.TemporaryDirectory() as d:
            seed = Path(d) / "resort_seed.csv"
            seed.write_text(self.HEADER + "Существующий,Регион1,,,\n", encoding="utf-8-sig")
            resorts = Path(d) / "resorts_manual.json"
            _write_json(resorts, {
                "resorts": [{"name_ru": "Новый", "region": "Регион2", "lat": 55.0, "lon": 37.0}],
            })
            added = merge_resorts_into_seed(resorts, seed)
            self.assertEqual(added, 1)
            lines = seed.read_text(encoding="utf-8-sig").strip().splitlines()
            self.assertEqual(len(lines), 3)  # header + 2 курорта

    def test_dedups_existing_resort_case_insensitive(self):
        with tempfile.TemporaryDirectory() as d:
            seed = Path(d) / "resort_seed.csv"
            seed.write_text(self.HEADER + "Тест Курорт,Регион1,,,\n", encoding="utf-8-sig")
            resorts = Path(d) / "resorts_manual.json"
            _write_json(resorts, {"resorts": [{"name_ru": "тест курорт", "region": "Регион2"}]})
            added = merge_resorts_into_seed(resorts, seed)
            self.assertEqual(added, 0)
            lines = seed.read_text(encoding="utf-8-sig").strip().splitlines()
            self.assertEqual(len(lines), 2)  # header + 1 курорт

    def test_empty_config_does_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            seed = Path(d) / "resort_seed.csv"
            seed.write_text(self.HEADER + "Тест,Регион,,,\n", encoding="utf-8-sig")
            resorts = Path(d) / "resorts_manual.json"
            _write_json(resorts, {"resorts": []})
            added = merge_resorts_into_seed(resorts, seed)
            self.assertEqual(added, 0)
            lines = seed.read_text(encoding="utf-8-sig").strip().splitlines()
            self.assertEqual(len(lines), 2)

    def test_missing_optional_fields_do_not_break(self):
        with tempfile.TemporaryDirectory() as d:
            seed = Path(d) / "resort_seed.csv"
            seed.write_text(self.HEADER, encoding="utf-8-sig")
            resorts = Path(d) / "resorts_manual.json"
            _write_json(resorts, {"resorts": [{"name_ru": "Только имя"}]})
            added = merge_resorts_into_seed(resorts, seed)
            self.assertEqual(added, 1)
            self.assertIn("Только имя,,,,", seed.read_text(encoding="utf-8-sig"))


class TestLoadPricesManual(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_prices_manual(Path(d) / "nope.json"), [])

    def test_empty_prices_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "prices_manual.json"
            _write_json(p, {"prices": []})
            self.assertEqual(load_prices_manual(p), [])


class TestLoadManualConfig(unittest.TestCase):
    def test_resolves_resort_name_to_id(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "resorts.json").write_text(
                json.dumps([
                    {"resort_id": "R001", "name_ru": "Роза Хутор"},
                    {"resort_id": "R002", "name_ru": "Новый Курорт"},
                ], ensure_ascii=False),
                encoding="utf-8",
            )
            entries = [{
                "resort_name": "Новый Курорт",
                "adult_price_min_rub": 3000,
                "adult_price_max_rub": 4500,
            }]
            with mock.patch.object(rp, "PREPARED", d), \
                 mock.patch.object(rp, "load_prices_manual", return_value=entries):
                rows = rp.load_manual_config()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["resort_id"], "R002")
            self.assertEqual(rows[0]["adult_price_min_rub"], 3000)
            self.assertEqual(rows[0]["source_quality"], "manual")

    def test_skips_unknown_resort(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "resorts.json").write_text(json.dumps([]), encoding="utf-8")
            entries = [{"resort_name": "Неизвестный", "adult_price_min_rub": 3000}]
            with mock.patch.object(rp, "PREPARED", d), \
                 mock.patch.object(rp, "load_prices_manual", return_value=entries):
                rows = rp.load_manual_config()
            self.assertEqual(rows, [])


class TestBuildRowsFallback(unittest.TestCase):
    def test_manual_config_used_when_parser_returns_nothing(self):
        manual_row = {
            "resort_id": "R999", "resort_name": "Тест", "month": None,
            "adult_price_min_rub": 3000, "adult_price_max_rub": 4500,
            "child_price_min_rub": None, "child_price_max_rub": None,
            "tariff_product": "Ски-пасс на 1 день", "coverage": None,
            "source_quality": "manual", "source_url": None, "checked_at": 1,
        }
        with mock.patch.object(rp, "run_parsers", return_value={}), \
             mock.patch.object(rp, "load_manual", return_value=[]), \
             mock.patch.object(rp, "load_manual_config", return_value=[manual_row]):
            rows = rp.build_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["resort_id"], "R999")
        self.assertEqual(rows[0]["adult_price_min_rub"], 3000)

    def test_manual_config_overrides_monthly(self):
        monthly_row = {
            "resort_id": "R001", "resort_name": "Роза", "month": "2026-01",
            "adult_price_min_rub": 5000, "adult_price_max_rub": 6000,
            "child_price_min_rub": None, "child_price_max_rub": None,
            "tariff_product": "Ски-пасс", "coverage": None,
            "source_quality": "secondary", "source_url": None, "checked_at": 1,
        }
        manual_row = {
            "resort_id": "R001", "resort_name": "Роза", "month": None,
            "adult_price_min_rub": 4200, "adult_price_max_rub": 4200,
            "child_price_min_rub": None, "child_price_max_rub": None,
            "tariff_product": "Ски-пасс на 1 день", "coverage": None,
            "source_quality": "manual", "source_url": "x", "checked_at": 1,
        }
        with mock.patch.object(rp, "run_parsers", return_value={}), \
             mock.patch.object(rp, "load_manual", return_value=[monthly_row]), \
             mock.patch.object(rp, "load_manual_config", return_value=[manual_row]):
            rows = rp.build_rows()
        # ручная цена перекрывает месячную матрицу (одна строка на курорт)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["adult_price_min_rub"], 4200)
        self.assertEqual(rows[0]["source_quality"], "manual")


class TestApplyCoordinatesSeedFallback(unittest.TestCase):
    def test_to_float(self):
        self.assertIsNone(ac._to_float(""))
        self.assertIsNone(ac._to_float(None))
        self.assertEqual(ac._to_float("55.5"), 55.5)

    def test_load_resorts_reads_lat_lon(self):
        with tempfile.TemporaryDirectory() as d:
            seed = Path(d) / "seed.csv"
            seed.write_text(
                "name_ru,region,settlement,lat,lon\nТест,Регион,Нас,55.5,37.7\n",
                encoding="utf-8-sig",
            )
            with mock.patch.object(ac, "SEED_CSV", seed):
                resorts = ac.load_resorts()
        self.assertEqual(resorts[0]["resort_id"], "R001")
        self.assertEqual(resorts[0]["settlement"], "Нас")
        self.assertEqual(resorts[0]["lat"], "55.5")
        self.assertEqual(resorts[0]["lon"], "37.7")

    def test_main_uses_seed_coordinates_as_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            seed = d / "seed.csv"
            seed.write_text(
                "name_ru,region,settlement,lat,lon\nТест,Регион,Нас,55.5,37.7\n",
                encoding="utf-8-sig",
            )
            with mock.patch.object(ac, "SEED_CSV", seed), \
                 mock.patch.object(ac, "PREPARED_DIR", d / "prepared"), \
                 mock.patch.object(ac, "COLLECTED_DIR", d / "collected"), \
                 mock.patch.object(ac, "load_verified", return_value={}), \
                 mock.patch.object(ac, "load_previous_prepared", return_value={}):
                ac.main()
            resorts = json.loads((d / "prepared" / "resorts.json").read_text(encoding="utf-8"))
        self.assertEqual(resorts[0]["coordinate_status"], "updated")
        self.assertEqual(resorts[0]["latitude"], 55.5)
        self.assertEqual(resorts[0]["longitude"], 37.7)


if __name__ == "__main__":
    unittest.main()
