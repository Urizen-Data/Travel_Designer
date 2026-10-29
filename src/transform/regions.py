"""Словарь регионов: приведение названий субъектов РФ к единому region_key.

Из ТЗ: «Названия субъектов приводятся к единому region_key через отдельный
словарь соответствий. Соединять таблицы по строкам, которые выглядят похоже,
нельзя.»

Канонический `region_key` совпадает с названием субъекта в справочнике курортов
(`resorts.json`). Все прочие написания (в первую очередь из Росстата/ЕМИСС)
приводятся к нему через нормализацию и явный словарь соответствий `ALIASES`.

Модуль использует только стандартную библиотеку (json, csv, pathlib), как и
основной расчёт эталона.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PREPARED_DIR = PROJECT_ROOT / "data" / "prepared"
REFERENCE_DIR = PROJECT_ROOT / "data" / "reference"

# Словарь соответствий: нормализованный вариант названия -> канонический region_key.
# Ключи записаны уже в нормализованной форме (дефисы приведены к "-", "ё" -> "е").
ALIASES: dict[str, str] = {
    # Росстат vs resorts.json
    "Кемеровская область - Кузбасс": "Кемеровская область",
    "Республика Северная Осетия - Алания": "Республика Северная Осетия — Алания",
    "Республика Северная Осетия-Алания": "Республика Северная Осетия — Алания",
    # Короткие формы республик (Nominatim и другие источники)
    "Карачаево-Черкесия": "Карачаево-Черкесская Республика",
    "Кабардино-Балкария": "Кабардино-Балкарская Республика",
    "Башкортостан": "Республика Башкортостан",
    "Хакасия": "Республика Хакасия",
    "Северная Осетия": "Республика Северная Осетия — Алания",
    "Северная Осетия - Алания": "Республика Северная Осетия — Алания",
    "Алтай": "Республика Алтай",
}


def _normalize(value: object) -> str:
    """Привести дефисы/пробелы/регистр к единому виду."""
    normalized = str(value).replace("–", "-").replace("—", "-").replace("ё", "е")
    return " ".join(normalized.split()).strip()


def region_key(value: object) -> str:
    """Вернуть канонический region_key для названия субъекта РФ."""
    normalized = _normalize(value)
    return ALIASES.get(normalized, normalized)


# Псевдоним для совместимости с терминологией эталонного скрипта.
canonical_region = region_key


def _load_matrix(path: Path) -> tuple[list, list[dict]]:
    """Прочитать JSON-матрицу (первая строка — заголовки)."""
    matrix = json.loads(Path(path).read_text(encoding="utf-8"))
    header, rows = matrix[0], matrix[1:]
    return header, [dict(zip(header, row)) for row in rows]


def _load_rosstat_regions(path: Path) -> list[str]:
    """Извлечь названия регионов из CSV Росстата (колонка 'Ряд')."""
    regions: list[str] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file, delimiter=";"):
            # "Ряд" = "<регион> — <период>"; берём часть до последнего разделителя
            regions.append(row["Ряд"].rsplit(" — ", 1)[0].strip())
    return regions


def build_region_dictionary() -> dict:
    """Собрать словарь регионов из подготовленного справочника курортов.

    Возвращает структуру с регионами: для каждого — region_key, список
    resort_id и список написаний, встреченных в файлах Росстата.
    """
    resorts = json.loads((PREPARED_DIR / "resorts.json").read_text(encoding="utf-8"))

    rosstat_names: set[str] = set()
    for filename in ("rosstat_tourist_trips.csv", "rosstat_tourist_nights.csv"):
        rosstat_names.update(_load_rosstat_regions(RAW_DIR / filename))

    regions: dict[str, dict] = {}
    for resort in resorts:
        key = region_key(resort["region"])
        entry = regions.setdefault(
            key, {"region_key": key, "resort_ids": [], "rosstat_names": []}
        )
        entry["resort_ids"].append(resort["resort_id"])

    for name in sorted(rosstat_names):
        key = region_key(name)
        if key in regions and name not in regions[key]["rosstat_names"]:
            regions[key]["rosstat_names"].append(name)

    result = sorted(regions.values(), key=lambda item: item["region_key"])
    for entry in result:
        entry["resort_ids"] = sorted(entry["resort_ids"])
        entry["resort_count"] = len(entry["resort_ids"])

    return {
        "note": (
            "Словарь соответствий названий субъектов РФ -> region_key. "
            "region_key совпадает с названием субъекта в resorts.json."
        ),
        "aliases": ALIASES,
        "regions": result,
    }


def main() -> None:
    """Записать словарь регионов в data/reference/region_key.json."""
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_region_dictionary()
    out = REFERENCE_DIR / "region_key.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Регионов: {len(payload['regions'])}")
    print(f"Записано: {out}")


if __name__ == "__main__":
    main()
