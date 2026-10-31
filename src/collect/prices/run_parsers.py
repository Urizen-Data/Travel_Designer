#!/usr/bin/env python3
"""Сбор цен на ски-пассы: ручные + парсеры -> сводная матрица.

Объединяет (по убыванию приоритета):
  * ручные цены из data/raw/resorts_manual.json (source_quality="manual");
  * месячную матрицу из того же файла (source_quality="secondary"/"official");
  * живые скраперы parsers/parse_*.py (Шерегеш, Кукисвумчорр, Гора Белая).

Результат: data/prepared/prices.json — матрица «курорт × месяц».
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from src.collect.prices.parsers import (
    parse_gora_belaya,
    parse_kukisvumchorr,
    parse_sheregesh,
)  # noqa: E402
from src.collect.prices.parsers.base import clean, fetch  # noqa: E402
from src.collect.manual_inputs import load_manual_prices  # noqa: E402

PREPARED = PROJECT_ROOT / "data" / "prepared"
OUT = PREPARED / "prices.json"

HEADER = [
    "resort_id", "resort_name", "month",
    "adult_price_min_rub", "adult_price_max_rub",
    "child_price_min_rub", "child_price_max_rub",
    "tariff_product", "coverage", "source_quality", "source_url", "checked_at",
]

PARSERS = [parse_sheregesh, parse_kukisvumchorr, parse_gora_belaya]


def run_parsers() -> dict[str, dict]:
    result = {}
    for mod in PARSERS:
        try:
            html, _ = fetch(mod.URL)
            price = mod.extract(clean(html))
            result[mod.RESORT_ID] = {
                "name_ru": mod.NAME,
                "min": price["min"] if price else None,
                "max": price["max"] if price else None,
                "source": mod.URL,
                "status": "парсер" if price else "парсер: не нашёл цену",
            }
        except Exception as exc:  # noqa: BLE001
            result[mod.RESORT_ID] = {
                "name_ru": mod.NAME,
                "min": None, "max": None, "source": mod.URL,
                "status": f"парсер: ошибка {type(exc).__name__}",
            }
    return result


def today_iso() -> str:
    """Сегодняшняя дата в ISO ('YYYY-MM-DD') для checked_at скраперов."""
    return date.today().isoformat()


def build_rows() -> list[dict]:
    # Приоритет: manual (source_quality="manual") > месячная матрица
    # (secondary/official) > живые парсеры.
    prices = load_manual_prices()
    manual: dict[str, dict] = {}
    monthly: list[dict] = []
    for p in prices:
        if p.get("source_quality") == "manual":
            manual.setdefault(str(p["resort_id"]), p)
        else:
            monthly.append(p)

    rows = list(manual.values())
    manual_ids = set(manual)
    for p in monthly:
        if str(p["resort_id"]) in manual_ids:
            continue
        rows.append(p)

    covered = {str(r["resort_id"]) for r in rows}
    checked = today_iso()

    for rid, info in run_parsers().items():
        if rid in covered or info["min"] is None:
            continue
        rows.append({
            "resort_id": rid,
            "resort_name": info["name_ru"],
            "month": None,
            "adult_price_min_rub": info["min"],
            "adult_price_max_rub": info["max"],
            "child_price_min_rub": None,
            "child_price_max_rub": None,
            "tariff_product": "Ски-пасс на 1 день",
            "coverage": None,
            "source_quality": "scraper",
            "source_url": info["source"],
            "checked_at": checked,
        })
    return rows


def _configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main() -> None:
    _configure_stdout()
    rows = build_rows()
    PREPARED.mkdir(parents=True, exist_ok=True)
    matrix = [HEADER] + [[r.get(c) for c in HEADER] for r in rows]
    OUT.write_text(json.dumps(matrix, ensure_ascii=False, indent=1), encoding="utf-8")

    by: dict[str, dict] = {}
    for r in rows:
        e = by.setdefault(str(r["resort_id"]), {
            "name": r["resort_name"], "min": None, "max": None,
            "months": set(), "quality": set(),
        })
        if r["month"]:
            e["months"].add(r["month"])
        if r["adult_price_min_rub"] is not None:
            e["min"] = r["adult_price_min_rub"] if e["min"] is None else min(e["min"], r["adult_price_min_rub"])
        if r["adult_price_max_rub"] is not None:
            e["max"] = r["adult_price_max_rub"] if e["max"] is None else max(e["max"], r["adult_price_max_rub"])
        if r["source_quality"]:
            e["quality"].add(r["source_quality"])

    print(f"{'id':<6}{'курорт':<20}{'мин':>8}{'макс':>8}  {'мес':>3}  качество")
    for rid in sorted(by):
        e = by[rid]
        mn = f"{int(e['min'])}" if e["min"] is not None else "—"
        mx = f"{int(e['max'])}" if e["max"] is not None else "—"
        q = "+".join(sorted(e["quality"])) or "—"
        print(f"{rid:<6}{e['name']:<20}{mn:>8}{mx:>8}  {len(e['months']):>3}  {q}")

    with_price = sum(1 for e in by.values() if e["min"] is not None)
    print(f"\nС ценой: {with_price} курортов. Сохранено: {OUT}")


if __name__ == "__main__":
    main()
