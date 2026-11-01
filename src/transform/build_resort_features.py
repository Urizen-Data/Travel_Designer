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
    """Excel-серийная дата (46279) или ISO 'YYYY-MM-DD' → 'YYYY-MM-DD'."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text  # уже ISO-дата
    try:
        serial = float(text)
        return (datetime(1899, 12, 30) + timedelta(days=serial)).date().isoformat()
    except (TypeError, ValueError):
        return None


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


def _price_rank(source_quality: object) -> int:
    """Приоритет источника цены: manual > secondary/official > scraper > прочее (0)."""
    return {"manual": 3, "secondary": 2, "official": 2, "scraper": 1}.get(
        str(source_quality or "").strip().lower(), 0
    )


def _select_current_price_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Самая актуальная запись цены: выше приоритет качества, затем свежий сезон.

    Если у лучших записей нет сезона — берётся последняя в списке.
    """
    if not rows:
        return None
    best_rank = max(_price_rank(r.get("source_quality")) for r in rows)
    candidates = [r for r in rows if _price_rank(r.get("source_quality")) == best_rank]
    with_season = [
        (r, str(r.get("season") or "").strip())
        for r in candidates
        if (r.get("season") or "").strip()
    ]
    if with_season:
        return max(with_season, key=lambda item: item[1])[0]
    return candidates[-1]


def _to_number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _avg_price(row: dict[str, Any] | None) -> float | None:
    """Среднее (min + max) / 2 из выбранной записи (None, если цены нет)."""
    if row is None:
        return None
    mn = _to_number(row.get("adult_price_min_rub"))
    mx = _to_number(row.get("adult_price_max_rub"))
    if mn is None and mx is None:
        return None
    if mn is None:
        return mx
    if mx is None:
        return mn
    return (mn + mx) / 2


def aggregate_prices() -> dict[str, dict[str, Any]]:
    """adult_skipass_avg_rub = среднее (min+max)/2 самой актуальной цены + метаданные.

    Самую актуальную запись выбираем по приоритету source_quality
    (manual > secondary/official > scraper) и по самому свежему сезону.

    Метаданные нужны для честной подписи цены (ТЗ дашборда §3.1): сезон,
    тарифный продукт, покрытие сезонов, источник и дата проверки.
    """
    matrix = json.loads((PREPARED / "prices.json").read_text(encoding="utf-8"))
    rows = [dict(zip(matrix[0], r)) for r in matrix[1:]]

    seasons: dict[str, set[str]] = defaultdict(set)
    products: dict[str, set[str]] = defaultdict(set)
    sources: dict[str, set[str]] = defaultdict(set)
    qualities: dict[str, set[str]] = defaultdict(set)
    checked: dict[str, set[object]] = defaultdict(set)
    by_resort: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        rid = str(row["resort_id"])
        by_resort[rid].append(row)
        if row["season"] not in (None, ""):
            seasons[rid].add(row["season"])
        if row["tariff_product"] not in (None, ""):
            products[rid].add(row["tariff_product"])
        if row["source_url"] not in (None, ""):
            sources[rid].add(row["source_url"])
        if row["source_quality"] not in (None, ""):
            qualities[rid].add(row["source_quality"])
        if row["checked_at"] not in (None, ""):
            checked[rid].add(row["checked_at"])

    result: dict[str, dict[str, Any]] = {}
    for rid in by_resort:
        s = sorted(seasons.get(rid, set()))
        iso_checked = [c for c in (_excel_serial_to_iso(x) for x in checked.get(rid, set())) if c]
        result[rid] = {
            "adult_skipass_avg_rub": _avg_price(_select_current_price_row(by_resort[rid])),
            "price_months_count": len(s),
            "price_months_min": s[0] if s else None,
            "price_months_max": s[-1] if s else None,
            "price_season": "; ".join(s) or None,
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
