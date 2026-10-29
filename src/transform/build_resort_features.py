#!/usr/bin/env python3
"""Витрина resort_features: одна строка = один курорт.

Соединяет по resort_id (регион приводится к region_key внутри скрипта для джойна с Росстатом):
  * курорты (data/prepared/resorts.json) — координаты, OSM, климат, аэропорт, качество;
  * региональный спрос (data/prepared/region_metrics.json) — поездки, рост, длительность;
  * цены (data/prepared/prices.json) → adult_skipass_avg_rub + price_months_count.

Проверки: 32 строки, 32 уникальных resort_id, нет пропусков trips_2025,
соединение без размножения строк.

Результат: data/mart/resort_features.csv.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Статус валидации координаты (качество) по статусу этапа геокодинга.
# «warn» (сдвиг 8–15 км) не приравнивается к подтверждённой координате.
COORDINATE_VALIDATION_STATUS = {
    "updated": "confirmed",
    "warn": "provisional",
    "needs_review": "needs_review",
}


def coordinate_validation_status(status: str | None) -> str:
    return COORDINATE_VALIDATION_STATUS.get(status, "needs_review")


def _excel_serial_to_iso(value: object) -> str | None:
    """Excel-серийная дата (например, 46279) → ISO-дата 'YYYY-MM-DD'."""
    try:
        serial = float(value)
        return (datetime(1899, 12, 30) + timedelta(days=serial)).date().isoformat()
    except (TypeError, ValueError):
        return None


def _season_of_month(month: str) -> str:
    """Месяц 'YYYY-MM' → зимний сезон 'YYYY/YY' (ноябрь–декабрь открывают сезон)."""
    year, m = int(month[:4]), int(month[5:7])
    return f"{year}/{str(year + 1)[2:]}" if m >= 11 else f"{year - 1}/{str(year)[2:]}"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.transform.regions import region_key  # noqa: E402
from src.common.mart_io import write_csv  # noqa: E402

PREPARED = PROJECT_ROOT / "data" / "prepared"
MART = PROJECT_ROOT / "data" / "mart"

# Поля курорта, которые переносятся в витрину как есть (для скоринга и отчёта)
RESORT_FIELDS = [
    "latitude", "longitude", "coordinate_quality_new", "coordinate_status",
    "piste_segments_6km", "lift_lines_6km", "lodging_objects_6km",
    "food_objects_6km", "attraction_objects_6km", "transport_objects_6km",
    "piste_ways_total", "piste_length_km",
    "piste_difficulty_novice", "piste_difficulty_easy", "piste_difficulty_intermediate",
    "piste_difficulty_advanced", "piste_difficulty_expert", "piste_difficulty_freeride",
    "piste_difficulty_unknown",
    "piste_type_nordic", "piste_type_snow_park",
    "piste_type_other", "piste_difficulty_coverage",
    "piste_min_elevation_m", "piste_max_elevation_m",
    "avg_snowfall_cm_per_season", "avg_freezing_days_per_season",
    "avg_snow_days_per_season", "max_daily_snowfall_cm",
    "winter_mean_temperature_c", "open_meteo_elevation_m",
    "nearest_airport_distance_km", "nearest_airport_iata",
    "completeness_pct", "quality_flags", "osm_overlap_warning",
    "openskimap_id", "openskimap_name", "official_website_url", "openskimap_sources",
    "skimap_id", "skimap_url",
    "details_url", "details_url_source",
]

REGION_FIELDS = [
    "trips_2022", "trips_2023", "trips_2024", "trips_2025",
    "nights_2023", "nights_2024", "nights_2025",
    "trips_growth_2025", "avg_stay_nights_2025",
]


def load_resorts() -> list[dict[str, Any]]:
    return json.loads((PREPARED / "resorts.json").read_text(encoding="utf-8"))


def load_region_metrics() -> dict[str, dict[str, Any]]:
    payload = json.loads((PREPARED / "region_metrics.json").read_text(encoding="utf-8"))
    return {r["region_key"]: r for r in payload["regions"]}


def aggregate_prices() -> dict[str, dict[str, Any]]:
    """adult_skipass_avg_rub = среднее всех min/max + метаданные цены.

    Метаданные нужны для честной подписи цены (ТЗ дашборда §3.1): сезон,
    тарифный продукт, покрытие месяцев, источник и дата проверки.
    """
    matrix = json.loads((PREPARED / "prices.json").read_text(encoding="utf-8"))
    rows = [dict(zip(matrix[0], r)) for r in matrix[1:]]

    values: dict[str, list[float]] = defaultdict(list)
    months: dict[str, set[str]] = defaultdict(set)
    products: dict[str, set[str]] = defaultdict(set)
    sources: dict[str, set[str]] = defaultdict(set)
    qualities: dict[str, set[str]] = defaultdict(set)
    checked: dict[str, set[object]] = defaultdict(set)

    for row in rows:
        rid = str(row["resort_id"])
        if row["adult_price_min_rub"] not in (None, ""):
            values[rid].append(float(row["adult_price_min_rub"]))
        if row["adult_price_max_rub"] not in (None, ""):
            values[rid].append(float(row["adult_price_max_rub"]))
        if row["month"] not in (None, ""):
            months[rid].add(row["month"])
        if row["tariff_product"] not in (None, ""):
            products[rid].add(row["tariff_product"])
        if row["source_url"] not in (None, ""):
            sources[rid].add(row["source_url"])
        if row["source_quality"] not in (None, ""):
            qualities[rid].add(row["source_quality"])
        if row["checked_at"] not in (None, ""):
            checked[rid].add(row["checked_at"])

    result: dict[str, dict[str, Any]] = {}
    for rid, vals in values.items():
        m = sorted(months.get(rid, set()))
        seasons = {_season_of_month(x) for x in m}
        iso_checked = [c for c in (_excel_serial_to_iso(x) for x in checked.get(rid, set())) if c]
        result[rid] = {
            "adult_skipass_avg_rub": sum(vals) / len(vals) if vals else None,
            "price_months_count": len(m),
            "price_months_min": m[0] if m else None,
            "price_months_max": m[-1] if m else None,
            "price_season": "; ".join(sorted(seasons)) or None,
            "price_product": "; ".join(sorted(products.get(rid, set()))) or None,
            "price_source_quality": "; ".join(sorted(qualities.get(rid, set()))) or None,
            "price_source_url": "; ".join(sorted(sources.get(rid, set()))) or None,
            "price_checked_at": max(iso_checked) if iso_checked else None,
        }
    return result


def build_resort_features() -> list[dict[str, Any]]:
    resorts = load_resorts()
    regions = load_region_metrics()
    prices = aggregate_prices()

    features: list[dict[str, Any]] = []
    for r in resorts:
        key = region_key(r["region"])
        reg = regions[key]
        p = prices.get(r["resort_id"], {"adult_skipass_avg_rub": None, "price_months_count": 0})

        row: dict[str, Any] = {
            "resort_id": r["resort_id"],
            "name_ru": r["name_ru"],
            "region": r["region"],
        }
        for field in RESORT_FIELDS:
            row[field] = r.get(field)
        for field in REGION_FIELDS:
            row[field] = reg.get(field)
        row["coordinate_validation_status"] = coordinate_validation_status(r.get("coordinate_status"))
        for key in (
            "adult_skipass_avg_rub",
            "price_months_count",
            "price_months_min",
            "price_months_max",
            "price_season",
            "price_product",
            "price_source_quality",
            "price_source_url",
            "price_checked_at",
        ):
            row[key] = p.get(key)
        features.append(row)
    return features


def main() -> None:
    features = build_resort_features()

    # обязательные проверки (N = число курортов в справочнике)
    n_resorts = len(load_resorts())
    assert len(features) == n_resorts, f"ожидалось {n_resorts} строк, получено {len(features)}"
    ids = [f["resort_id"] for f in features]
    assert len(set(ids)) == n_resorts, "resort_id должны быть уникальны"
    missing_trips = [f["resort_id"] for f in features if f["trips_2025"] is None]
    assert not missing_trips, f"нет trips_2025 у: {missing_trips}"

    MART.mkdir(parents=True, exist_ok=True)
    out = MART / "resort_features.csv"
    write_csv(out, features)

    with_price = sum(1 for f in features if f["adult_skipass_avg_rub"] is not None)
    print(f"resort_features: {len(features)} строк, {len(set(ids))} уникальных resort_id")
    print(f"с ценой: {with_price}, без цены: {len(features) - with_price}")
    print(f"Сохранено: {out}")


if __name__ == "__main__":
    main()
