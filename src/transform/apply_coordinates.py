#!/usr/bin/env python3
"""Собрать справочник курортов из resorts_manual.json (название + регион) с координатами.

Читает data/raw/resorts_manual.json (name_ru, region, resort_id), берёт проверенные
координаты из data/collected/coordinates_verified.json и валидирует регион координаты
обратным геокодингом Nominatim против региона курорта.

Правила:
  * регион совпал          -> применяем координаты, статус "updated";
  * регион не совпал       -> не применяем, статус "needs_review";
  * координаты нет (review)-> "needs_review".

Результат:
  * data/prepared/resorts.json            — курорты (id + name + region + координаты + статус);
  * data/collected/coordinates_review.json — очередь ручной проверки.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.collect.manual_inputs import load_resorts_manual  # noqa: E402
from src.transform.regions import region_key  # noqa: E402

PREPARED_DIR = PROJECT_ROOT / "data" / "prepared"
COLLECTED_DIR = PROJECT_ROOT / "data" / "collected"

NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "TravelDesignerStudentWorkshop/1.0 open-data-research"


def load_resorts() -> list[dict[str, Any]]:
    """Справочник курортов из resorts_manual.json (единый источник правды).

    resort_id берётся из JSON (стабильный); если его нет — присваивается по
    порядку. lat/lon из JSON используются как точные координаты (fallback),
    если в coordinates_verified.json нет записи.
    """
    resorts: list[dict[str, Any]] = []
    for index, r in enumerate(load_resorts_manual(), start=1):
        resorts.append({
            "resort_id": r.get("resort_id") or f"R{index:03d}",
            "name_ru": (r.get("name_ru") or "").strip(),
            "region": (r.get("region") or "").strip(),
            "settlement": (r.get("settlement") or "").strip(),
            "lat": r.get("lat"),
            "lon": r.get("lon"),
            "official_website_url": r.get("official_website_url"),
            "details_url": r.get("details_url"),
            "skimap_url": r.get("skimap_url"),
        })
    return resorts


def _to_float(value: str | None) -> float | None:
    """Строку/None в float; None, если пусто или не число."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_verified() -> dict[str, dict[str, Any]]:
    path = COLLECTED_DIR / "coordinates_verified.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {r["resort_id"]: r for r in payload["resorts"]}


# Поля, собранные recompute (OSM/климат/аэропорт/трассы), которые переносим из
# прошлого прогона как базовую линию, чтобы при падении Overpass они не обнулялись.
CARRY_FIELDS = [
    "piste_segments_6km", "lift_lines_6km", "lodging_objects_6km", "food_objects_6km",
    "transport_objects_6km", "attraction_objects_6km", "osm_radius_km", "osm_overlap_warning",
    "open_meteo_elevation_m", "winter_mean_temperature_c", "avg_snowfall_cm_per_season",
    "avg_freezing_days_per_season", "avg_snow_days_per_season", "max_daily_snowfall_cm",
    "weather_model", "weather_period_start", "weather_period_end",
    "nearest_scheduled_airport", "nearest_airport_iata", "nearest_airport_distance_km",
    "nearest_airport_municipality", "completeness_pct", "quality_flags",
    "piste_ways_total", "piste_difficulty_novice", "piste_difficulty_easy",
    "piste_difficulty_intermediate", "piste_difficulty_advanced", "piste_difficulty_expert",
    "piste_difficulty_freeride", "piste_difficulty_extreme", "piste_difficulty_unknown",
    "piste_type_nordic", "piste_type_skitour", "piste_type_snow_park", "piste_type_sled",
    "piste_type_other", "piste_difficulty_coverage",
    "data_recomputed_at", "osm_data_timestamp", "piste_data_timestamp",
]

# Ручные поля из resorts_manual.json (источник правды): перезаписываем каждый
# прогон, а не переносим из прошлого prepared (чтобы ручное удаление значения
# тоже подхватывалось).
MANUAL_FIELDS = ["official_website_url", "details_url", "skimap_url"]


def load_previous_prepared() -> dict[str, dict[str, Any]]:
    """Прошлый prepared/resorts.json (результат recompute) → {resort_id: поля}."""
    path = PREPARED_DIR / "resorts.json"
    if not path.exists():
        return {}
    return {r["resort_id"]: r for r in json.loads(path.read_text(encoding="utf-8"))}


def reverse_region(lat: float, lon: float) -> str | None:
    """Субъект РФ по координате через обратный геокодинг Nominatim."""
    params = urllib.parse.urlencode(
        {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 6}
    )
    url = f"{NOMINATIM_REVERSE}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("address", {}).get("state")


def main() -> None:
    resorts = load_resorts()
    verified = load_verified()
    reference_data = load_previous_prepared()

    prepared: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []

    for resort in resorts:
        rid = resort["resort_id"]
        info = verified.get(rid, {})
        chosen = info.get("chosen")
        quality_new = info.get("quality_new")
        prev = reference_data.get(rid, {})

        row: dict[str, Any] = {
            "resort_id": rid,
            "name_ru": resort["name_ru"],
            "region": resort["region"],
            "latitude": None,
            "longitude": None,
            "coordinate_quality_new": quality_new,
            "coordinate_region_check": None,
            "coordinate_status": None,
            "coordinate_review_reason": None,
        }
        # Переносим собранные recompute данные (OSM/климат/аэропорт) из прошлого
        # прогона, чтобы при недоступном Overpass они не обнулялись.
        for field in CARRY_FIELDS:
            row[field] = prev.get(field)
        # Ручные поля (сайт/ссылки) всегда берём из resorts_manual.json.
        for field in MANUAL_FIELDS:
            row[field] = resort.get(field)

        if chosen is None:
            # Fallback: точные координаты из seed (ручное добавление через
            # resorts_manual.json). Используются напрямую, без обратного геокодинга.
            seed_lat = _to_float(resort.get("lat"))
            seed_lon = _to_float(resort.get("lon"))
            if seed_lat is not None and seed_lon is not None:
                row["latitude"] = seed_lat
                row["longitude"] = seed_lon
                row["coordinate_quality_new"] = quality_new or "manual_seed"
                row["coordinate_status"] = "updated"
                row["coordinate_review_reason"] = None
                prepared.append(row)
                continue
            row["coordinate_status"] = "needs_review"
            row["coordinate_review_reason"] = "нет проверенной координаты"
            review.append(_review_entry(row, "нет проверенной координаты"))
            prepared.append(row)
            continue

        new_lat = float(chosen["latitude"])
        new_lon = float(chosen["longitude"])

        # Регион новой координаты (независимая проверка)
        region_check = "unknown"
        state = None
        try:
            state = reverse_region(new_lat, new_lon)
            if state is not None:
                region_check = (
                    "ok" if region_key(state) == region_key(resort["region"]) else "mismatch"
                )
        except Exception as exc:  # noqa: BLE001 — сеть/лимит не критичны
            region_check = "unknown"
            print(f"  [reverse] {rid}: {type(exc).__name__}", flush=True)
        time.sleep(1.1)
        row["coordinate_region_check"] = region_check

        if region_check == "mismatch":
            row["coordinate_status"] = "needs_review"
            row["coordinate_review_reason"] = f"регион не совпал: {state}"
        else:
            row["coordinate_status"] = "updated"
            row["coordinate_review_reason"] = None
            row["latitude"] = new_lat
            row["longitude"] = new_lon

        if row["coordinate_status"] == "needs_review":
            review.append(_review_entry(row, row["coordinate_review_reason"]))
        prepared.append(row)

    PREPARED_DIR.mkdir(parents=True, exist_ok=True)
    (PREPARED_DIR / "resorts.json").write_text(
        json.dumps(prepared, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    COLLECTED_DIR.mkdir(parents=True, exist_ok=True)
    (COLLECTED_DIR / "coordinates_review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _print_summary(prepared)


def _review_entry(row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "resort_id": row["resort_id"],
        "name_ru": row["name_ru"],
        "region": row["region"],
        "quality_new": row.get("coordinate_quality_new"),
        "region_check": row.get("coordinate_region_check"),
        "reason": reason,
    }


def _print_summary(rows: list[dict[str, Any]]) -> None:
    print(f"\n{'id':<6}{'статус':<13}  {'регион':<10} курорт")
    for r in rows:
        rc = r.get("coordinate_region_check") or "-"
        print(f"{r['resort_id']:<6}{r['coordinate_status']:<13}  {rc:<10} {r['name_ru']}")
    n = len(rows)
    n_updated = sum(1 for r in rows if r["coordinate_status"] == "updated")
    n_review = sum(1 for r in rows if r["coordinate_status"] == "needs_review")
    print(f"\nПрименено: {n_updated}, на проверку: {n_review}, всего: {n}")


if __name__ == "__main__":
    main()
