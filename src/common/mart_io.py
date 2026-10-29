"""Чтение/запись витрин в CSV (папка data/mart).

Используется UTF-8 с BOM (utf-8-sig), чтобы кириллица корректно открывалась
в Excel. Пустая строка <-> None, числовые значения восстанавливаются в
int/float при чтении, поэтому код, работавший с JSON, работает без изменений.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Записать список словарей в CSV. None -> пустая строка."""
    if not rows:
        path.write_text("", encoding="utf-8-sig", newline="")
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})


def _convert(value: str) -> Any:
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def read_csv(path: Path) -> list[dict[str, Any]]:
    """Прочитать CSV в список словарей: '' -> None, числа -> int/float."""
    with open(path, encoding="utf-8-sig", newline="") as file:
        return [
            {k: _convert(v) for k, v in row.items()} for row in csv.DictReader(file)
        ]
