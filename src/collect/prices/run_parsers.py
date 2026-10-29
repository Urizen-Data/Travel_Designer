"""Сбор цен на ски-пассы: ручные + парсеры -> сводная матрица.

Объединяет (по убыванию приоритета):
  * ручные цены data/raw/prices_manual.json (проверены вручную, приоритет);
  * мануальную матрицу data/raw/prices_monthly.json (по месяцам);
  * живые скраперы parsers/parse_*.py (Шерегеш, Кукисвумчорр, Гора Белая).

Результат: data/prepared/prices.json — та же матрица «курорт × месяц», что и
prices_monthly.json, дополненная строками ручных цен и скраперов (month=None,
source_quality="manual"/"scraper", tariff_product="Ски-пасс на 1 день").
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
from src.collect.manual_inputs import load_prices_manual  # noqa: E402

RAW = PROJECT_ROOT / "data" / "raw"
PREPARED = PROJECT_ROOT / "data" / "prepared"
OUT = PREPARED / "prices.json"

HEADER = [
    "resort_id", "resort_name", "month",
    "adult_price_min_rub", "adult_price_max_rub",
    "child_price_min_rub", "child_price_max_rub",
    "tariff_product", "coverage", "source_quality", "source_url", "checked_at",
]

PARSERS = [parse_sheregesh, parse_kukisvumchorr, parse_gora_belaya]


def load_matrix(path: Path) -> list[dict]:
    m = json.loads(Path(path).read_text(encoding="utf-8"))
    return [dict(zip(m[0], r)) for r in m[1:]]


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


def load_manual() -> list[dict]:
    return load_matrix(RAW / "prices_monthly.json")


def load_manual_config() -> list[dict]:
    """Ручные цены из data/raw/prices_manual.json, привязанные к resort_id по name_ru.

    Возвращает строки в том же формате, что и prices_monthly.json. Записи, для
    которых не удалось определить resort_id (курорт не найден в resorts.json),
    пропускаются с предупреждением.
    """
    entries = load_prices_manual()
    if not entries:
        return []

    name_to_id: dict[str, str] = {}
    resorts_path = PREPARED / "resorts.json"
    if resorts_path.exists():
        try:
            for r in json.loads(resorts_path.read_text(encoding="utf-8")):
                name = (r.get("name_ru") or "").strip().lower()
                rid = r.get("resort_id")
                if name and rid:
                    name_to_id[name] = str(rid)
        except (json.JSONDecodeError, OSError):
            pass

    rows: list[dict] = []
    for entry in entries:
        name = (entry.get("resort_name") or "").strip()
        rid = entry.get("resort_id") or name_to_id.get(name.lower())
        if not rid:
            print(
                f"[prices_manual] курорт не найден в resorts.json: '{name}' — пропущено",
                flush=True,
            )
            continue
        rows.append({
            "resort_id": str(rid),
            "resort_name": name or str(rid),
            "month": entry.get("month"),
            "adult_price_min_rub": entry.get("adult_price_min_rub"),
            "adult_price_max_rub": entry.get("adult_price_max_rub"),
            "child_price_min_rub": entry.get("child_price_min_rub"),
            "child_price_max_rub": entry.get("child_price_max_rub"),
            "tariff_product": entry.get("tariff_product") or "Ски-пасс на 1 день",
            "coverage": entry.get("coverage"),
            "source_quality": entry.get("source_quality") or "manual",
            "source_url": entry.get("source_url"),
            "checked_at": (
                entry.get("checked_at")
                if entry.get("checked_at") is not None
                else today_serial()
            ),
        })
    return rows


def today_serial() -> int:
    """Сегодняшняя дата в Excel-сериале (как checked_at в мануальном файле)."""
    return (date.today() - date(1899, 12, 30)).days


def build_rows() -> list[dict]:
    # Приоритет: prices_manual.json (ручные, проверенные) > prices_monthly.json > парсеры.
    rows = list(load_manual_config())
    manual_config_ids = {str(r["resort_id"]) for r in rows}

    for r in load_manual():  # prices_monthly.json (матрица)
        if str(r["resort_id"]) in manual_config_ids:
            continue  # ручная цена из prices_manual.json приоритетнее
        rows.append(r)

    covered = {str(r["resort_id"]) for r in rows}
    checked = today_serial()

    for rid, info in run_parsers().items():
        if rid in covered or info["min"] is None:
            continue  # уже есть цена (ручная/месячная) или скрапер без цены
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

    # сводка: один курорт = одна строка (мин/макс по всем месяцам)
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
