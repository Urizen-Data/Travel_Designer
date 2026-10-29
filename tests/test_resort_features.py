"""Проверки витрины resort_features."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.transform.build_resort_features import build_resort_features


class TestResortFeatures(unittest.TestCase):
    def setUp(self):
        self.features = build_resort_features()

    def test_32_unique_resorts(self):
        self.assertEqual(len(self.features), 32)
        ids = [f["resort_id"] for f in self.features]
        self.assertEqual(len(ids), len(set(ids)))

    def test_no_missing_trips_2025(self):
        for f in self.features:
            self.assertIsNotNone(f["trips_2025"], f["resort_id"])
            self.assertGreater(f["trips_2025"], 0)

    def test_region_join_no_row_multiplication(self):
        # 20 регионов, но 32 строки (не размножаются)
        regions = {f["region"] for f in self.features}
        self.assertLessEqual(len(regions), 20)

    def test_price_aggregation(self):
        # у курортов с ценой avg > 0; без цены — помесячных данных нет (months == 0)
        for f in self.features:
            if f["adult_skipass_avg_rub"] is not None:
                self.assertGreater(f["adult_skipass_avg_rub"], 0)
            else:
                self.assertEqual(f["price_months_count"], 0)

    def test_required_scoring_fields_present(self):
        required = [
            "piste_segments_6km", "lift_lines_6km", "lodging_objects_6km",
            "avg_snowfall_cm_per_season", "avg_freezing_days_per_season",
            "avg_snow_days_per_season", "nearest_airport_distance_km",
            "transport_objects_6km", "trips_growth_2025", "avg_stay_nights_2025",
        ]
        for f in self.features:
            for field in required:
                self.assertIn(field, f)

    def test_validation_status_mapping_function(self):
        from src.transform.build_resort_features import coordinate_validation_status
        self.assertEqual(coordinate_validation_status("updated"), "confirmed")
        self.assertEqual(coordinate_validation_status("warn"), "provisional")
        self.assertEqual(coordinate_validation_status("needs_review"), "needs_review")
        self.assertEqual(coordinate_validation_status(None), "needs_review")
        self.assertEqual(coordinate_validation_status("unknown"), "needs_review")

    def test_coordinate_validation_status(self):
        expected = {"updated": "confirmed", "warn": "provisional", "needs_review": "needs_review"}
        for f in self.features:
            self.assertIn(f["coordinate_validation_status"], ("confirmed", "provisional", "needs_review"))
            self.assertEqual(f["coordinate_validation_status"], expected[f["coordinate_status"]], f["resort_id"])

    def test_price_metadata(self):
        for f in self.features:
            if f["price_months_count"] > 0:
                for key in ("price_season", "price_product", "price_source_url", "price_checked_at",
                            "price_months_min", "price_months_max"):
                    self.assertIsNotNone(f[key], f"{f['resort_id']}.{key}")
                self.assertLessEqual(f["price_months_min"], f["price_months_max"])
            elif f["adult_skipass_avg_rub"] is not None:
                # скрапер: цена и источник есть, но помесячной разбивки нет
                self.assertIsNotNone(f["price_source_url"], f["resort_id"])
                self.assertIsNotNone(f["price_source_quality"], f["resort_id"])
                self.assertIsNone(f["price_season"], f["resort_id"])
                self.assertEqual(f["price_months_count"], 0)


if __name__ == "__main__":
    unittest.main()
