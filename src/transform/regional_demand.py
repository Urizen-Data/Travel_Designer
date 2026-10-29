#!/usr/bin/env python3
"""Региональный спрос: агрегация Росстата до «регион × год».

Читает rosstat_tourist_trips.csv и rosstat_tourist_nights.csv, приводит названия
субъектов РФ к region_key, агрегирует до одной строки на регион и год и считает
два производных показателя:

  trips_growth_2025    = trips_2025 / trips_2024 - 1
  avg_stay_nights_2025 = nights_2025 / trips_2025

Логика повторяет эталонный prepare_model_data.py:
  * поездки: период «январь-декабрь»  -> годы 2023/2024/2025;
             период «январь-декабрь*» -> год 2022 (отдельный ряд с меткой «*»);
  * ночёвки: период «январь-декабрь»  -> годы 2023/2024/2025.

Результат: data/prepared/region_metrics.json.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.transform.regions import region_key  # noqa: E402

RAW_DIR = PROJECT_ROOT / "data" / "raw"
PREPARED_DIR = PROJECT_ROOT / "data" / "prepared"

TRIPS_YEARS = (2023, 2024, 2025)
NIGHTS_YEARS = (2023, 2024, 2025)


def read_rosstat(path: Path) -> list[dict[str, Any]]:
    """Прочитать CSV Росстата (разделитель ';', кодировка utf-8-sig)."""
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file, delimiter=";"):
            clean: dict[str, Any] = {"series": row["Ряд"]}
            for key, value in row.items():
                if key == "Ряд":
                    continue
                clean[key] = float(value) if value not in (None, "") else None
            rows.append(clean)
    return rows


def split_series(value: str) -> tuple[str, str]:
    """Разбить «регион — период» на части по последнему разделителю."""
    region, period = value.rsplit(" — ", 1)
    return region.strip(), period.strip()


def load_resort_regions() -> set[str]:
    """Канонические region_key регионов из подготовленного справочника курортов."""
    resorts = json.loads((PREPARED_DIR / "resorts.json").read_text(encoding="utf-8"))
    return {region_key(r["region"]) for r in resorts}


def build_region_metrics() -> list[dict[str, Any]]:
    """Агрегировать Росстат до одной строки на регион + производные показатели."""
    regions_needed = sorted(load_resort_regions())
    metrics: dict[str, dict[str, Any]] = {
        region: {
            "region_key": region,
            "trips_2022": None,
            "trips_2023": None,
            "trips_2024": None,
            "trips_2025": None,
            "nights_2023": None,
            "nights_2024": None,
            "nights_2025": None,
        }
        for region in regions_needed
    }

    trips_rows = read_rosstat(RAW_DIR / "rosstat_tourist_trips.csv")
    for row in trips_rows:
        region_raw, period = split_series(str(row["series"]))
        region = region_key(region_raw)
        if region not in metrics:
            continue
        if period == "январь-декабрь":
            for year in TRIPS_YEARS:
                metrics[region][f"trips_{year}"] = row.get(str(year))
        elif period == "январь-декабрь*":
            metrics[region]["trips_2022"] = row.get("2022")

    nights_rows = read_rosstat(RAW_DIR / "rosstat_tourist_nights.csv")
    for row in nights_rows:
        region_raw, period = split_series(str(row["series"]))
        region = region_key(region_raw)
        if region not in metrics or period != "январь-декабрь":
            continue
        for year in NIGHTS_YEARS:
            metrics[region][f"nights_{year}"] = row.get(str(year))

    result: list[dict[str, Any]] = []
    for region, record in metrics.items():
        trips_2024 = record["trips_2024"]
        trips_2025 = record["trips_2025"]
        nights_2025 = record["nights_2025"]
        record["trips_growth_2025"] = (
            trips_2025 / trips_2024 - 1.0 if trips_2024 and trips_2025 else None
        )
        record["avg_stay_nights_2025"] = (
            nights_2025 / trips_2025 if nights_2025 and trips_2025 else None
        )
        result.append(record)
    return result


def main() -> None:
    metrics = build_region_metrics()
    missing_trips = [m["region_key"] for m in metrics if not m["trips_2025"]]
    if missing_trips:
        raise RuntimeError(f"Нет trips_2025 для регионов: {missing_trips}")

    PREPARED_DIR.mkdir(parents=True, exist_ok=True)
    out = PREPARED_DIR / "region_metrics.json"
    out.write_text(
        json.dumps(
            {"note": "Региональный спрос: агрегация Росстата до «регион × год».",
             "regions": metrics},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Регионов: {len(metrics)}, с trips_2025: {sum(1 for m in metrics if m['trips_2025'])}")
    print(f"Записано: {out}")


if __name__ == "__main__":
    main()
