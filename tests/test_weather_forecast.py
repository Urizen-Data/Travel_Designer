"""Проверки правила оценки состояния трассы."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.collect.fetch_weather_forecast import classify_slope, classify_slope_explained


class TestSlopeCondition(unittest.TestCase):
    def test_fresh_snow(self):
        self.assertEqual(classify_slope(15.0, 0.0, -5.0, -9.0, 0.5), "предпосылки свежего рыхлого снега")

    def test_groomed_becomes_insufficient(self):
        # отсутствие снегопада не означает накат — оценки недостаточно
        self.assertEqual(classify_slope(0.0, 0.0, -4.0, -8.0, 0.6), "оценки недостаточно")

    def test_wet(self):
        self.assertEqual(classify_slope(0.0, 3.0, 3.0, 0.0, 0.4), "предпосылки увлажнения/размягчения")

    def test_ice(self):
        self.assertEqual(classify_slope(0.0, 0.0, 1.0, -5.0, 0.2), "предпосылки замерзания")

    def test_no_snow(self):
        self.assertEqual(classify_slope(0.0, 0.0, 5.0, 1.0, 0.0), "модель не показывает естественный снежный покров")

    def test_light_snow(self):
        self.assertEqual(classify_slope(4.0, 0.0, -2.0, -6.0, 0.35), "предпосылки свежего рыхлого снега")

    def test_explained_returns_reason_and_limitations(self):
        cond, reason, limits = classify_slope_explained(0.0, 3.0, 3.0, 0.0, 0.4)
        self.assertEqual(cond, "предпосылки увлажнения/размягчения")
        self.assertTrue(reason)
        self.assertTrue(limits)


if __name__ == "__main__":
    unittest.main()
