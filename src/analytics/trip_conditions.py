#!/usr/bin/env python3
"""Разворот прогноза в плоскую таблицу + мягкие категории + причины/свежесть.

Читает data/collected/weather_forecast.json, переклассифицирует состояние
трассы мягкими формулировками (ТЗ дашборда §5.3) и разворачивает «курорт ×
10 дней» в плоскую таблицу «курорт × дата прогноза».

Для каждого дня добавляются:
  * slope_condition        — мягкая категория (предпосылки, не факт поверхности);
  * condition_reason       — причина из фактических условий правила;
  * condition_limitations  — ограничение оценки;
  * fetched_at, rule_version, model — метаданные пакета прогноза.

Свежесть (текущее время − fetched_at) и признак устаревания вычисляются на
стороне BI, а не зашиваются в статичный JSON (ТЗ дашборда §8).

Выход: data/mart/weather_forecast_daily.csv.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.collect.fetch_weather_forecast import classify_slope_explained  # noqa: E402
from src.common.mart_io import write_csv  # noqa: E402

COLLECTED = PROJECT_ROOT / "data" / "collected"
ANALYTICS = PROJECT_ROOT / "data" / "mart"

RULE_VERSION = "2.0"
STALENESS_HOURS_THRESHOLD = 12

VALID_CONDITIONS = {
    "модель не показывает естественный снежный покров",
    "предпосылки свежего рыхлого снега",
    "предпосылки увлажнения/размягчения",
    "предпосылки замерзания",
    "оценки недостаточно",
}


def load_forecast() -> dict[str, Any]:
    return json.loads((COLLECTED / "weather_forecast.json").read_text(encoding="utf-8"))


def build_daily_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    fetched_at = payload.get("fetched_at")
    rows: list[dict[str, Any]] = []
    for resort in payload.get("resorts", []):
        if "error" in resort or not resort.get("days"):
            continue
        for day in resort.get("days", []):
            cond, reason, limits = classify_slope_explained(
                day.get("snowfall_cm"),
                day.get("rain_mm"),
                day.get("temperature_max_c"),
                day.get("temperature_min_c"),
                day.get("snow_depth_m"),
            )
            rows.append(
                {
                    "resort_id": resort["resort_id"],
                    "name_ru": resort["name_ru"],
                    "region": resort["region"],
                    "date": day.get("date"),
                    "fetched_at": fetched_at,
                    "elevation_m": resort.get("elevation_m"),
                    "resort_elevation_m": resort.get("resort_elevation_m"),
                    "snowfall_cm": day.get("snowfall_cm"),
                    "rain_mm": day.get("rain_mm"),
                    "temperature_min_c": day.get("temperature_min_c"),
                    "temperature_max_c": day.get("temperature_max_c"),
                    "weather_code": day.get("weather_code"),
                    "wind_gusts_max_kmh": day.get("wind_gusts_max_kmh"),
                    "snow_depth_m": day.get("snow_depth_m"),
                    "freezing_level_min_m": day.get("freezing_level_min_m"),
                    "slope_condition": cond,
                    "condition_reason": reason,
                    "condition_limitations": limits,
                    "strong_wind": day.get("strong_wind"),
                }
            )
    return rows


def validate(rows: list[dict[str, Any]]) -> None:
    assert rows, "нет строк прогноза"
    for r in rows:
        assert r["slope_condition"] in VALID_CONDITIONS, f"{r['resort_id']}: {r['slope_condition']}"
        assert r["condition_reason"], r["resort_id"]
        assert r["condition_limitations"], r["resort_id"]
        assert r["date"], r["resort_id"]


def _configure_stdout() -> None:
    """UTF-8 для вывода, иначе символы вроде Δ/× падают в консоли cp1251."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main() -> None:
    _configure_stdout()
    payload = load_forecast()
    rows = build_daily_rows(payload)
    validate(rows)

    ANALYTICS.mkdir(parents=True, exist_ok=True)
    out = ANALYTICS / "weather_forecast_daily.csv"
    write_csv(out, rows)
    print(f"Прогноз: {len(rows)} строк (курорт × дата), курортов: {len({r['resort_id'] for r in rows})}")
    print(f"Сохранено: {out}")


if __name__ == "__main__":
    main()
