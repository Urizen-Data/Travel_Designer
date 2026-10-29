"""Ручные конфиги (курорты + цены) и слияние в seed.

Два JSON-файла в data/raw/ (дополняют существующие resort_seed.csv и
prices_monthly.json, а не заменяют их — принцип «не плодить сущности»):

  * resorts_manual.json — ручное добавление курортов:
        {"resorts": [{"name_ru": "...", "region": "...",
                      "settlement": "...", "lat": 55.0, "lon": 37.0}]}
        name_ru и region обязательны; lat/lon необязательны (если указаны оба —
        используются как точные координаты, иначе — геокодинг).

  * prices_manual.json — ручные цены ски-пассов (fallback, если парсер не нашёл):
        {"prices": [{"resort_name": "...", "adult_price_min_rub": 3000,
                     "adult_price_max_rub": 4500, "month": null,
                     "tariff_product": "Ски-пасс на 1 день", "source_quality": "manual"}]}
        Привязка к курорту — по resort_name (name_ru) или явному resort_id.

Все функции принимают необязательные пути, чтобы их можно было тестировать
на временных файлах.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw"

RESORTS_MANUAL = RAW_DIR / "resorts_manual.json"
PRICES_MANUAL = RAW_DIR / "prices_manual.json"
SEED_CSV = RAW_DIR / "resort_seed.csv"

# Канонический порядок колонок seed.csv (совпадает с текущим файлом).
RESORT_FIELDS = ["name_ru", "region", "settlement", "lat", "lon"]


def load_resorts_manual(path: Path | None = None) -> list[dict[str, Any]]:
    """Курорты из resorts_manual.json (список под ключом "resorts")."""
    path = path or RESORTS_MANUAL
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("resorts", []))


def load_prices_manual(path: Path | None = None) -> list[dict[str, Any]]:
    """Цены из prices_manual.json (список под ключом "prices")."""
    path = path or PRICES_MANUAL
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("prices", []))


def merge_resorts_into_seed(
    resorts_path: Path | None = None,
    seed_path: Path | None = None,
) -> int:
    """Дописать курорты из resorts_manual.json в конец seed.csv (без дублей по name_ru).

    Возвращает количество добавленных строк. Существующие курорты не трогаются.
    Сравнение имён — без учёта регистра и лишних пробелов.
    """
    resorts_path = resorts_path or RESORTS_MANUAL
    seed_path = seed_path or SEED_CSV
    manual = load_resorts_manual(resorts_path)
    if not manual:
        return 0

    seed_path.parent.mkdir(parents=True, exist_ok=True)
    if not seed_path.exists():
        fieldnames = list(RESORT_FIELDS)
        seed_rows: list[dict[str, str]] = []
    else:
        with open(seed_path, encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            fieldnames = list(reader.fieldnames or RESORT_FIELDS)
            seed_rows = [dict(row) for row in reader]

    existing = {(r.get("name_ru") or "").strip().lower() for r in seed_rows}
    added = 0
    for entry in manual:
        name = (entry.get("name_ru") or "").strip()
        if not name or name.lower() in existing:
            continue
        seed_rows.append({
            "name_ru": name,
            "region": (entry.get("region") or "").strip(),
            "settlement": (entry.get("settlement") or "").strip(),
            "lat": entry.get("lat") if entry.get("lat") is not None else "",
            "lon": entry.get("lon") if entry.get("lon") is not None else "",
        })
        existing.add(name.lower())
        added += 1

    if added:
        with open(seed_path, "w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(seed_rows)
    return added
