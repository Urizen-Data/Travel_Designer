#!/usr/bin/env python3
"""Загрузка витрин data/mart/*.csv в Supabase (PostgreSQL).

Для каждой витрины (CSV -> таблица с тем же именем):
  1. CREATE TABLE IF NOT EXISTS — типы колонок выводятся по данным + ключи (PK/FK) из TABLE_KEYS;
  2. DELETE FROM — очистка данных (в порядке, обратном зависимостям: дочерние раньше родителей);
  3. массовая вставка (execute_values), None -> NULL — в порядке зависимостей.

Таблицы обновляются на месте (не удаляются), поэтому view поверх них не разрушаются.
Pipeline управляет только таблицами; view создаются аналитиком в SQL Lab и не трогаются.

Вывод типов: bool -> BOOLEAN, int -> BIGINT, float -> DOUBLE PRECISION,
дата -> DATE, timestamp -> TIMESTAMPTZ, иначе TEXT.

Колонки НЕ хардкодятся — они берутся из заголовка CSV (поля могут появляться/исчезать).
Ключи задаются декларативно в TABLE_KEYS (ниже) поверх выведенных колонок; если ключевая
колонка отсутствует в CSV, соответствующий ключ пропускается с предупреждением.

Подключение читается из .env (DATABASE_URL). Пароль в код/Git не попадает.

Запуск отдельно от пайплайна:
    python src/load/load_supabase.py [таблица1 таблица2 ...]
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402
import psycopg2  # noqa: E402
from psycopg2.extras import execute_values  # noqa: E402

from src.common.mart_io import read_csv  # noqa: E402

MART_DIR = PROJECT_ROOT / "data" / "mart"

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

# ---------------------------------------------------------------------------
# Ключи таблиц (только ключи; перечень колонок берётся из CSV, не хардкодится).
# pk  — столбцы первичного ключа;
# fk  — (столбец_таблицы, родительская_таблица, столбец_родителя).
# resort_scores и catalog_scenarios — корневые таблицы, на которые ссылаются остальные.
# ---------------------------------------------------------------------------
TABLE_KEYS: dict[str, dict] = {
    "resort_scores": {"pk": ["resort_id"]},
    "catalog_scenarios": {"pk": ["scenario_id"]},

    "resort_features": {"pk": ["resort_id"], "fk": [("resort_id", "resort_scores", "resort_id")]},
    "resort_components": {"pk": ["resort_id", "component"], "fk": [("resort_id", "resort_scores", "resort_id")]},
    "ranking_stability": {"pk": ["resort_id", "preset_id"], "fk": [("resort_id", "resort_scores", "resort_id")]},
    "resort_reasons": {"pk": ["resort_id", "reason_code"], "fk": [("resort_id", "resort_scores", "resort_id")]},
    "catalog_members": {
        "pk": ["scenario_id", "resort_id"],
        "fk": [
            ("scenario_id", "catalog_scenarios", "scenario_id"),
            ("resort_id", "resort_scores", "resort_id"),
        ],
    },
    "climate_monthly": {"pk": ["resort_id", "month"], "fk": [("resort_id", "resort_scores", "resort_id")]},
    "weather_forecast_daily": {"pk": ["resort_id", "date"], "fk": [("resort_id", "resort_scores", "resort_id")]},
    "presets": {"pk": ["preset_id"]},
    "scoring_weights": {"pk": ["indicator"]},
    "resort_preset_components": {
        "pk": ["preset_id", "resort_id", "component"],
        "fk": [
            ("preset_id", "presets", "preset_id"),
            ("resort_id", "resort_scores", "resort_id"),
        ],
    },
    # Денормализованная read-таблица для Страницы 1 (без FK).
    "atlas_catalog": {"pk": ["scenario_id", "resort_id", "preset_id"]},
}


def _quote(name: str) -> str:
    """Экранировать имя таблицы/колонки двойными кавычками."""
    return '"' + name.replace('"', '""') + '"'


def _infer_type(values: list) -> str:
    """Вывести тип колонки PostgreSQL по её значениям."""
    non_null = [v for v in values if v is not None]
    if not non_null:
        return "TEXT"
    if all(isinstance(v, str) and v in ("True", "False") for v in non_null):
        return "BOOLEAN"
    if all(isinstance(v, int) for v in non_null):
        return "BIGINT"
    if all(isinstance(v, (int, float)) for v in non_null):
        return "DOUBLE PRECISION"
    if all(isinstance(v, str) and ISO_DATE.match(v) for v in non_null):
        return "DATE"
    if all(isinstance(v, str) and ISO_DATETIME.match(v) for v in non_null):
        return "TIMESTAMPTZ"
    return "TEXT"


def _coerce(value, col_type: str):
    """Привести значение к типу колонки перед вставкой."""
    if value is None:
        return None
    if col_type == "BOOLEAN":
        return value == "True"
    return value


def _connect():
    load_dotenv(PROJECT_ROOT / ".env")
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("В .env нет DATABASE_URL — заполните .env перед запуском")
    return psycopg2.connect(url, sslmode="require", connect_timeout=20)


def _topo_order(tables: list[str]) -> list[str]:
    """Вернуть таблицы так, чтобы родительские шли раньше дочерних."""
    deps = {
        t: {fk[1] for fk in TABLE_KEYS.get(t, {}).get("fk", []) if fk[1] in tables}
        for t in tables
    }

    ordered: list[str] = []
    remaining = set(tables)
    while remaining:
        ready = sorted(t for t in remaining if deps[t] <= set(ordered))
        if not ready:  # защита от цикла в конфигурации ключей
            ready = sorted(remaining)
        for t in ready:
            ordered.append(t)
            remaining.discard(t)
    return ordered


def _get_table_columns(cursor, table: str) -> set[str] | None:
    """Колонки существующей таблицы (None, если таблицы нет)."""
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s",
        (table,),
    )
    cols = [r[0] for r in cursor.fetchall()]
    return set(cols) if cols else None


def _create_table(cursor, table: str, columns: list[str], col_types: dict, keys: dict) -> None:
    """CREATE TABLE IF NOT EXISTS: выведенные из CSV колонки + ключи (PK/FK) из TABLE_KEYS."""
    col_defs = [f"{_quote(c)} {col_types[c]}" for c in columns]

    pk = keys.get("pk") or []
    missing_pk = [c for c in pk if c not in columns]
    if pk and not missing_pk:
        col_defs.append(f"PRIMARY KEY ({', '.join(_quote(c) for c in pk)})")
    elif missing_pk:
        print(f"  [warn] {table}: PK-колонки {missing_pk} отсутствуют в CSV — PK пропущен")

    for col, parent, parent_col in keys.get("fk", []):
        if col in columns:
            col_defs.append(
                f"FOREIGN KEY ({_quote(col)}) REFERENCES public.{_quote(parent)} ({_quote(parent_col)})"
            )
        else:
            print(f"  [warn] {table}: FK-колонка {col} отсутствует в CSV — FK пропущен")

    cursor.execute(f"CREATE TABLE IF NOT EXISTS public.{_quote(table)} ({', '.join(col_defs)})")


def _insert_table(cursor, table: str, columns: list[str], col_types: dict, rows: list) -> int:
    """Массовая вставка строк (execute_values, None -> NULL)."""
    col_list = ", ".join(_quote(c) for c in columns)
    data = [[_coerce(r[c], col_types[c]) for c in columns] for r in rows]
    execute_values(
        cursor,
        f"INSERT INTO public.{_quote(table)} ({col_list}) VALUES %s",
        data,
    )
    return len(rows)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # Таблицы — позиционными аргументами (python load_supabase.py a b c).
    # Без аргументов грузятся все витрины data/mart/*.csv.
    wanted = set(sys.argv[1:])

    conn = _connect()
    all_csv = sorted(MART_DIR.glob("*.csv"))
    paths = [p for p in all_csv if not wanted or p.stem in wanted]
    if not paths:
        print("Нет CSV для загрузки (data/mart пуст или имена таблиц не совпали).")
        conn.close()
        return

    # Читаем витрины: колонки и типы выводятся из CSV, ключи — из TABLE_KEYS.
    tables: dict = {}
    for p in paths:
        rows = read_csv(p)
        if not rows:
            continue
        columns = list(rows[0].keys())
        col_types = {c: _infer_type([r[c] for r in rows]) for c in columns}
        tables[p.stem] = {"columns": columns, "col_types": col_types, "rows": rows}

    ordered = _topo_order(list(tables.keys()))

    print(f"Загружаю {len(ordered)} витрин: {ordered}")
    if wanted:
        skipped = sorted({p.stem for p in all_csv} - set(ordered))
        if skipped:
            print(f"Пропускаю остальные (не относятся к текущему режиму): {skipped}")
    total = 0
    try:
        with conn:
            with conn.cursor() as cur:
                # 1) Проверить схему: при несовпадении колонок — DROP (дети раньше).
                for table in reversed(ordered):
                    t = tables[table]
                    db_cols = _get_table_columns(cur, table)
                    if db_cols is not None and set(t["columns"]) != db_cols:
                        cur.execute(f"DROP TABLE public.{_quote(table)}")
                        print(f"  [schema] {table}: колонки изменились — пересоздана")
                # 2) Создать отсутствующие таблицы (в порядке зависимостей).
                for table in ordered:
                    t = tables[table]
                    _create_table(cur, table, t["columns"], t["col_types"], TABLE_KEYS.get(table, {}))
                # 3) Очистить данные (в порядке, обратном зависимостям).
                for table in reversed(ordered):
                    cur.execute(f"DELETE FROM public.{_quote(table)}")
                # 4) INSERT в порядке зависимостей.
                for table in ordered:
                    t = tables[table]
                    n = _insert_table(cur, table, t["columns"], t["col_types"], t["rows"])
                    print(f"  {table}: {n} строк")
                    total += n
    finally:
        conn.close()

    print(f"\nЗагружено: {total} строк в {len(ordered)} таблиц.")


if __name__ == "__main__":
    main()
