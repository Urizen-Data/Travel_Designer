"""Единый ручной конфиг курортов: data/raw/resorts_manual.json.

Один источник правды по курортам. Внутри каждого курорта — вложенный список
цен (prices) и ссылки. Пустые поля заполняются фолбэками пайплайна:
  * lat/lon                -> геокодинг (OpenSkiMap -> Wikidata -> Overpass);
  * official_website_url   -> OpenSkiMap (websites);
  * details_url/skimap_url -> fetch_skimap_ids (Skimap -> Wikipedia -> Wikidata);
  * prices (если пусто)    -> живые парсеры parse_*.py.

Структура:
{
  "_comment": "...",
  "resorts": [
    {
      "resort_id": "R001",
      "name_ru": "Роза Хутор",
      "region": "Краснодарский край",
      "settlement": "Сочи",
      "lat": null, "lon": null,
      "official_website_url": null,
      "details_url": null,
      "skimap_url": null,
      "prices": [
        {"season": "2025-26", "adult_price_min_rub": 5550, "adult_price_max_rub": 6350,
         "child_price_min_rub": null, "child_price_max_rub": null,
         "tariff_product": "Ски-пасс на 1 день", "coverage": null,
         "source_quality": "manual", "source_url": "...", "checked_at": null}
      ]
    }
  ]
}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw"

RESORTS_MANUAL = RAW_DIR / "resorts_manual.json"

# Канонический набор полей курорта (для автодополнения пустыми значениями).
RESORT_FIELDS = [
    "resort_id", "name_ru", "region", "settlement", "lat", "lon",
    "official_website_url", "details_url", "skimap_url", "prices",
]


def load_resorts_manual(path: Path | None = None) -> list[dict[str, Any]]:
    """Все курорты из resorts_manual.json (список под ключом "resorts")."""
    path = path or RESORTS_MANUAL
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("resorts", []))


def load_manual_prices(path: Path | None = None) -> list[dict[str, Any]]:
    """Плоский список цен из resorts_manual.json.

    Каждая строка повторяет прежний формат матрицы цен (resort_id +
    resort_name + season + ценовые поля).
    """
    rows: list[dict[str, Any]] = []
    for r in load_resorts_manual(path):
        rid = r.get("resort_id")
        name = r.get("name_ru")
        for p in r.get("prices") or []:
            rows.append({
                "resort_id": rid,
                "resort_name": name,
                "season": p.get("season"),
                "adult_price_min_rub": p.get("adult_price_min_rub"),
                "adult_price_max_rub": p.get("adult_price_max_rub"),
                "child_price_min_rub": p.get("child_price_min_rub"),
                "child_price_max_rub": p.get("child_price_max_rub"),
                "tariff_product": p.get("tariff_product"),
                "coverage": p.get("coverage"),
                "source_quality": p.get("source_quality"),
                "source_url": p.get("source_url"),
                "checked_at": p.get("checked_at"),
            })
    return rows


def next_resort_id(resorts: list[dict[str, Any]] | None = None) -> str:
    """Следующий свободный resort_id (R###)."""
    resorts = resorts if resorts is not None else load_resorts_manual()
    max_n = 0
    for r in resorts:
        rid = str(r.get("resort_id") or "")
        if len(rid) >= 2 and rid[0].upper() == "R" and rid[1:].isdigit():
            max_n = max(max_n, int(rid[1:]))
    return f"R{max_n + 1:03d}"


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def write_resorts(resorts: list[dict[str, Any]], path: Path | None = None) -> None:
    """Записать resorts_manual.json, сохранив существующий _comment."""
    path = path or RESORTS_MANUAL
    comment = ""
    if path.exists():
        try:
            comment = json.loads(path.read_text(encoding="utf-8")).get("_comment", "")
        except (json.JSONDecodeError, OSError):
            comment = ""
    payload = {"_comment": comment, "resorts": resorts}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_resort(resort: dict[str, Any], path: Path | None = None) -> str:
    """Добавить курорт (без дублей по name_ru), вернуть его resort_id."""
    resorts = load_resorts_manual(path)
    name = _normalize(resort.get("name_ru"))
    for r in resorts:
        if _normalize(r.get("name_ru")) == name:
            return str(r.get("resort_id"))
    if not resort.get("resort_id"):
        resort["resort_id"] = next_resort_id(resorts)
    for field in RESORT_FIELDS:
        resort.setdefault(field, [] if field == "prices" else None)
    resorts.append(resort)
    write_resorts(resorts, path)
    return str(resort["resort_id"])


def _matches(rid: str, name: str, target: str) -> bool:
    rid = _normalize(rid)
    name = _normalize(name)
    rid_digits = rid[1:] if rid.startswith("r") else ""
    return rid == target or name == target or rid_digits == target


def update_resort(resort_id_or_name: str, updates: dict[str, Any], path: Path | None = None) -> bool:
    """Обновить поля курорта по resort_id или name_ru (без регистра)."""
    resorts = load_resorts_manual(path)
    target = _normalize(resort_id_or_name)
    found = False
    for r in resorts:
        if _matches(r.get("resort_id"), r.get("name_ru"), target):
            r.update(updates)
            found = True
    if found:
        write_resorts(resorts, path)
    return found


def remove_resort(resort_id_or_name: str, path: Path | None = None) -> dict[str, Any] | None:
    """Удалить курорт по resort_id или name_ru; вернуть удалённый dict или None."""
    resorts = load_resorts_manual(path)
    target = _normalize(resort_id_or_name)
    for i, r in enumerate(resorts):
        if _matches(r.get("resort_id"), r.get("name_ru"), target):
            removed = resorts.pop(i)
            write_resorts(resorts, path)
            return removed
    return None

