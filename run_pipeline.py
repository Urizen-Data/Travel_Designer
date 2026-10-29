#!/usr/bin/env python3
"""Оркестратор воспроизводимого ETL-пайплайна Travel Designer.

Запускает шаги сборка -> обработка -> скоринг -> аналитика -> загрузка в Supabase
в правильном порядке и останавливается на первой ошибке.

Режимы (--mode):
  full    — всё с нуля: координаты, пересбор OSM/климата (--force), рейтинг,
            прогноз погоды и загрузка всех витрин в Supabase;
  static  — статичная ветка «рейтинг»: вливает ручные курорты из
            data/raw/resorts_manual.json в seed, пересобирает справочник курортов,
            инкрементально обновляет OSM/климат, считает рейтинг и загружает
            результат в Supabase (погода не трогается);
  weather — только динамичная ветка «погода»: прогноз + разворот + загрузка;
  climate — только климат: 30-летняя норма (recompute --only-climate) +
            пересборка витрин рейтинга + загрузка;
  add     — интерактивно добавить курорт (название + регион) в seed и прогнать
            всю цепочку «рейтинг» для обновлённого списка;
  remove  — интерактивно удалить курорт из seed и кэша и пересобрать витрины
            рейтинга без него (с загрузкой в Supabase);
  rescore — локальный пересчёт рейтинга и пресетов из готовых данных (без
            сетевых запросов) и загрузка результата в Supabase.

Примеры:
  python run_pipeline.py --mode full
  python run_pipeline.py --mode static
  python run_pipeline.py --mode weather
  python run_pipeline.py --mode add
  python run_pipeline.py --mode remove
  python run_pipeline.py --mode rescore
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
sys.path.insert(0, str(PROJECT_ROOT))

from src.collect.geocode_resorts import OVERPASS_ENDPOINTS, USER_AGENT, assess_resort  # noqa: E402

# Шаги ветки «рейтинг» после сборки справочника курортов (apply_coordinates):
# инкрементальный пересчёт OSM/климата → обработка → скоринг → аналитика.
RATING_TAIL = [
    ("src/collect/recompute_resort_data.py",),
    ("src/transform/regional_demand.py",),
    ("src/collect/prices/run_parsers.py",),
    ("src/collect/fetch_skimap_ids.py",),
    ("src/transform/build_resort_features.py",),
    ("src/scoring/score_resorts.py",),
    ("src/scoring/preset_engine.py",),
    ("src/analytics/ranking_insights.py",),
    ("src/analytics/catalog_builder.py",),
    ("src/analytics/build_atlas_catalog.py",),
]

# Слияние ручных курортов (resorts_manual.json → resort_seed.csv) перед сборкой
# справочника: новые курорты из JSON подхватываются всеми ветками «рейтинг».
MERGE_RESORTS = ("src/collect/merge_resorts.py",)

# Шаги ветки «рейтинг», полный пересбор (координаты собираются заново).
RATING_FULL = [
    MERGE_RESORTS,
    ("src/collect/geocode_resorts.py",),
    ("src/transform/apply_coordinates.py",),
    *RATING_TAIL,
]

# Шаги ветки «рейтинг», инкрементально. Справочник курортов пересобирается из
# seed (после вливания ручных курортов), чтобы новые курорты из resorts_manual.json
# появлялись в витринах; OSM/трассы не пересобираются.
RATING_STATIC = [
    MERGE_RESORTS,
    ("src/transform/apply_coordinates.py",),
    *RATING_TAIL,
]

# Шаги ветки «погода».
# Шаги режима «add»: как full, но OSM/трассы не пересобираются (инкрементально).
RATING_ADD = [
    MERGE_RESORTS,
    ("src/collect/geocode_resorts.py",),
    ("src/transform/apply_coordinates.py",),
    *RATING_TAIL,
]

WEATHER = [
    ("src/collect/fetch_weather_forecast.py",),
    ("src/analytics/trip_conditions.py",),
]

# Шаги режима «климат»: только 30-летний климат + пересборка зависимых витрин.
CLIMATE = [
    ("src/collect/recompute_resort_data.py", "--only-climate"),
    ("src/transform/build_resort_features.py",),
    ("src/scoring/score_resorts.py",),
    ("src/scoring/preset_engine.py",),
    ("src/analytics/ranking_insights.py",),
    ("src/analytics/catalog_builder.py",),
    ("src/analytics/build_atlas_catalog.py",),
]

# Шаги режима «remove»: пересобрать справочник из seed (без удалённого курорта),
# затем пересчитать витрины рейтинга (как static) и загрузить.
REMOVE = [
    MERGE_RESORTS,
    ("src/transform/apply_coordinates.py",),
    *RATING_TAIL,
]

# Шаги режима «rescore»: локальный пересчёт рейтинга и пресетов из готовых данных.
# Единственный сетевой шаг — load_supabase в конце. Остальное читает data/*/*.csv/json.
RATING_RESCORE = [
    ("src/transform/build_resort_features.py",),
    ("src/scoring/score_resorts.py",),
    ("src/scoring/preset_engine.py",),
    ("src/analytics/ranking_insights.py",),
    ("src/analytics/catalog_builder.py",),
    ("src/analytics/build_atlas_catalog.py",),
]

LOAD = ("src/load/load_supabase.py",)

# Погода ни от чего не зависит по FK — грузим только её. Остальные режимы
# грузят все витрины: таблицы скоринга связаны внешними ключами с
# climate_monthly/weather_forecast_daily (через resort_scores), поэтому
# выборочная загрузка здесь сломает DELETE (ForeignKeyViolation).
LOAD_WEATHER = ("src/load/load_supabase.py", "weather_forecast_daily")

# Шаги, которым нужен Overpass: перед ними выполняем pre-flight проверку доступности.
OVERPASS_SCRIPTS = {"src/collect/geocode_resorts.py", "src/collect/recompute_resort_data.py"}

# Скрипты, делающие HTTP-запросы к внешним сервисам (запрещены в режиме rescore).
NETWORK_SCRIPTS = {
    "src/collect/geocode_resorts.py",
    "src/transform/apply_coordinates.py",
    "src/collect/recompute_resort_data.py",
    "src/transform/regional_demand.py",
    "src/collect/prices/run_parsers.py",
    "src/collect/fetch_skimap_ids.py",
    "src/collect/fetch_weather_forecast.py",
}

MODES = {
    "full": RATING_FULL + WEATHER + [LOAD],
    "static": RATING_STATIC + [LOAD],
    "weather": WEATHER + [LOAD_WEATHER],
    "climate": CLIMATE + [LOAD],
    "add": RATING_ADD + [LOAD],
    "remove": REMOVE + [LOAD],
    "rescore": RATING_RESCORE + [LOAD],
}

# Эти режимы читают data/prepared/resorts.json, который создаёт полный прогон.
NEEDS_PREPARED = {"static", "weather", "rescore"}


def _configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def run_step(script: str, *args: str) -> None:
    cmd = [PYTHON, str(PROJECT_ROOT / script), *args]
    label = script + (f" {' '.join(args)}" if args else "")
    print(f"\n=== {label} ===", flush=True)
    if script == LOAD[0]:
        print("[load] начало загрузки в Supabase ...", flush=True)
    start = time.time()
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"  # русский вывод в дочерних процессах не падает
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env)
    elapsed = time.time() - start
    print(f"[step] {label}: {elapsed:.1f} с", flush=True)
    if result.returncode != 0:
        raise SystemExit(f"[ОСТАНОВКА] шаг завершился с кодом {result.returncode}: {label}")
    if script == LOAD[0]:
        print("[load] загрузка в Supabase завершена", flush=True)


def _assert_no_network_steps(steps: list[tuple]) -> None:
    """Проверить, что в шагах нет сетевых скриптов (кроме load_supabase)."""
    offenders = [s[0] for s in steps if s[0] in NETWORK_SCRIPTS]
    if offenders:
        raise SystemExit(
            f"[rescore] в цепочке найдены сетевые скрипты: {', '.join(offenders)}. "
            "Режим rescore должен быть полностью локальным (кроме load_supabase)."
        )


def append_resort_to_seed(
    name: str, region: str, settlement: str = "", lat: str = "", lon: str = ""
) -> None:
    """Дописать курорт (название + регион + нас.пункт + опц. координаты) в конец seed."""
    seed = PROJECT_ROOT / "data" / "raw" / "resort_seed.csv"
    with open(seed, "a", encoding="utf-8", newline="") as file:
        csv.writer(file).writerow([name, region, settlement, lat, lon])


def set_resort_anchor(name: str, lat: str, lon: str) -> bool:
    """Обновить lat/lon (seed-якорь) у существующего курорта (по имени, без регистра).

    Возвращает True, если курорт найден и обновлён; иначе False.
    """
    seed = PROJECT_ROOT / "data" / "raw" / "resort_seed.csv"
    target = name.strip().lower()
    rows: list[dict[str, str]] = []
    found = False
    with open(seed, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if (row.get("name_ru") or "").strip().lower() == target:
                row["lat"] = lat
                row["lon"] = lon
                found = True
            rows.append(row)
    if found:
        with open(seed, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    return found


def _load_seed() -> tuple[list[str], list[dict[str, str]]]:
    """(header, rows) из data/raw/resort_seed.csv."""
    seed = PROJECT_ROOT / "data" / "raw" / "resort_seed.csv"
    with open(seed, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames or [], [dict(row) for row in reader]


def _write_seed(header: list[str], rows: list[dict[str, str]]) -> None:
    seed = PROJECT_ROOT / "data" / "raw" / "resort_seed.csv"
    with open(seed, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def _find_resort(rows: list[dict[str, str]], query: str) -> tuple[int, dict[str, str]] | None:
    """Найти курорт в seed по name_ru или resort_id (R###/###/число)."""
    q = query.strip().lstrip("\ufeff").lower()
    for index, row in enumerate(rows):
        rid = f"R{index + 1:03d}"
        if (
            rid.lower() == q
            or rid[-3:] == q
            or str(index + 1) == q
            or (row.get("name_ru") or "").strip().lower() == q
        ):
            return index, row
    return None


def _shift_resort_id(rid: str, removed_n: int) -> str | None:
    """Новый resort_id после удаления resort #removed_n (None = удалить запись)."""
    s = str(rid).strip()
    if len(s) >= 2 and s[0].upper() == "R" and s[1:].isdigit():
        n = int(s[1:])
        if n == removed_n:
            return None
        if n > removed_n:
            return f"R{n - 1:03d}"
    return s


def _compact_order_based_data(removed_n: int) -> None:
    """Удалить resort и сдвинуть последующие resort_id на -1 в order-based файлах.

    resort_id присваивается по порядку строк seed (apply_coordinates), поэтому после
    удаления строки из середины все последующие id сдвигаются. Синхронно обновляем
    файлы, закешированные по resort_id, чтобы не было рассинхрона.
    """
    def shift(rid: str) -> str | None:
        return _shift_resort_id(rid, removed_n)

    # data/cache/climate_daily.json: {resort_id: [дневные строки]}
    cache = PROJECT_ROOT / "data" / "cache" / "climate_daily.json"
    if cache.exists():
        payload = json.loads(cache.read_text(encoding="utf-8"))
        shifted: dict[str, list] = {}
        for rid, rows in payload.items():
            new_rid = shift(rid)
            if new_rid is not None:
                shifted[new_rid] = rows
        cache.write_text(json.dumps(shifted, ensure_ascii=False), encoding="utf-8")

    # data/collected/coordinates_verified.json: {"resorts": [{resort_id, ...}]}
    verified = PROJECT_ROOT / "data" / "collected" / "coordinates_verified.json"
    if verified.exists():
        payload = json.loads(verified.read_text(encoding="utf-8"))
        kept = []
        for r in payload.get("resorts", []):
            new_rid = shift(r.get("resort_id", ""))
            if new_rid is None:
                continue
            if new_rid != r.get("resort_id"):
                r = dict(r)
                r["resort_id"] = new_rid
            kept.append(r)
        payload["resorts"] = kept
        verified.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # data/prepared/resorts.json: [{resort_id, ...}] (базовая линия для carry-over)
    prepared = PROJECT_ROOT / "data" / "prepared" / "resorts.json"
    if prepared.exists():
        resorts = json.loads(prepared.read_text(encoding="utf-8"))
        kept = []
        for r in resorts:
            new_rid = shift(r.get("resort_id", ""))
            if new_rid is None:
                continue
            if new_rid != r.get("resort_id"):
                r = dict(r)
                r["resort_id"] = new_rid
            kept.append(r)
        prepared.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")

    # data/raw/prices_monthly.json: [header, [resort_id, ...], ...]
    prices = PROJECT_ROOT / "data" / "raw" / "prices_monthly.json"
    if prices.exists():
        matrix = json.loads(prices.read_text(encoding="utf-8"))
        header = matrix[0]
        col = header.index("resort_id") if "resort_id" in header else 0
        kept = []
        for row in matrix[1:]:
            new_rid = shift(str(row[col]))
            if new_rid is None:
                continue
            if new_rid != str(row[col]):
                row = list(row)
                row[col] = new_rid
            kept.append(row)
        prices.write_text(json.dumps([header] + kept, ensure_ascii=False, indent=2), encoding="utf-8")


def _remove_resort(header: list[str], rows: list[dict[str, str]], index: int) -> tuple[str, str]:
    """Удалить курорт из seed и order-based файлов; вернуть (resort_id, name_ru)."""
    rid = f"R{index + 1:03d}"
    name = (rows[index].get("name_ru") or "").strip()
    _write_seed(header, [r for i, r in enumerate(rows) if i != index])
    _compact_order_based_data(index + 1)
    return rid, name


def print_assessment(result: dict) -> None:
    print("\n=== Оценка полноты данных ===")
    if result["chosen"]:
        c = result["chosen"]
        print(f"Координаты: {result['quality']} ({c['latitude']:.5f}, {c['longitude']:.5f})  [OK]")
    else:
        print(f"Координаты: не найдены ({result['quality']})  [ОШИБКА]")
    rosstat = "есть" if result["region_in_rosstat"] else "НЕТ"
    mark = "OK" if result["region_in_rosstat"] else "ОШИБКА"
    print(f"Регион:     {result['region']} — trips_2025 {rosstat}  [{mark}]")
    print("Цена:       не будет найдена (нейтральный балл 50)  [WARN]")
    print("OpenSkiMap/OSM/климат/аэропорт: соберутся при добавлении")
    print("Ссылка (Skimap/Wikipedia/Wikidata): соберётся при добавлении")
    ok = result["chosen"] is not None and result["region_in_rosstat"]
    print("\n→ Вердикт: " + ("можно добавить" if ok else "НЕЛЬЗЯ добавить"))


def check_overpass(timeout: int = 30) -> tuple[int, list[str]]:
    """Лёгкая проверка доступности зеркал Overpass.

    Возвращает (число живых зеркал, список строк статуса).
    """
    query = "[out:json][timeout:15];node(43.6,40.2,43.7,40.4)[aerialway];out count;"
    alive = 0
    status: list[str] = []
    for endpoint, verify_ssl in OVERPASS_ENDPOINTS:
        context = None
        if not verify_ssl:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        body = urllib.parse.urlencode({"data": query}).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        host = endpoint.split("/")[2]
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            total = payload.get("elements", [{}])[0].get("tags", {}).get("total", 0)
            if total:
                alive += 1
                status.append(f"  [ok, {total} об.]  {host}")
            else:
                status.append(f"  [пусто]  {host}")
        except urllib.error.HTTPError as exc:
            status.append(f"  [{exc.code}] {host}")
        except Exception as exc:  # noqa: BLE001 — таймаут/сеть/SSL
            status.append(f"  [{type(exc).__name__}] {host}")
    return alive, status


def _confirm_overpass_down() -> bool:
    """Интерактивный выбор при недоступном Overpass (pre-flight).

    Возвращает True — продолжить пайплайн, False — прервать.
      * y / yes / да        → True (продолжить);
      * n / Enter / пусто   → False (прервать);
      * EOFError (нет консоли, напр. CI/CD) → True (как раньше);
      * таймаут 30 с        → False (по умолчанию N).
    """
    prompt = (
        "ВНИМАНИЕ: Overpass недоступен. Продолжить выполнение пайплайна "
        "(данные OSM будут пропущены)? [y/N]: "
    )
    print(prompt, end="", flush=True)

    result: list[str | None] = []

    def _read() -> None:
        try:
            result.append(input())
        except EOFError:
            result.append(None)

    thread = threading.Thread(target=_read, daemon=True)
    thread.start()
    thread.join(timeout=30)

    if thread.is_alive():
        # Таймаут: пользователь не ответил за 30 с — по умолчанию N (прервать).
        print()
        return False

    answer = result[0] if result else None
    if answer is None:
        # Неинтерактивный режим (EOFError) — продолжаем как раньше.
        return True
    return answer.strip().lower() in ("y", "yes", "да")


def main() -> None:
    _configure_stdout()
    parser = argparse.ArgumentParser(description="Оркестратор ETL-пайплайна")
    parser.add_argument("--mode", choices=sorted(MODES), required=True, help="режим запуска")
    parser.add_argument("--name", type=str, default="", help="название или resort_id курорта (для --mode add/remove)")
    parser.add_argument("--region", type=str, default="", help="регион курорта (для --mode add)")
    parser.add_argument("--settlement", type=str, default="", help="населённый пункт (для --mode add)")
    parser.add_argument("--no-load", action="store_true", help="не загружать в Supabase (только локальные файлы)")
    parser.add_argument("--skip-overpass-check", action="store_true", help="не проверять доступность Overpass перед прогоном")
    parser.add_argument("--force", action="store_true", help="перегеокодировать координаты и пересобрать OSM заново (игнорировать инкрементальность)")
    args = parser.parse_args()

    if args.mode == "add":
        name = args.name.strip() if args.name else input("Название курорта: ").strip()
        region = args.region.strip() if args.region else input("Регион: ").strip()
        settlement = (
            args.settlement.strip()
            if args.settlement
            else input("Населённый пункт (необязательно): ").strip()
        )
        if not name or not region:
            raise SystemExit("Название и регион обязательны")

        # Необязательные координаты (якорь для OSM-уточнения)
        coord_raw = input("Координаты (широта,долгота — необязательно): ").strip()
        lat_s = lon_s = ""
        lat_f = lon_f = None
        if coord_raw:
            parts = [p.strip() for p in coord_raw.replace(" ", "").split(",")]
            if len(parts) >= 2:
                lat_s, lon_s = parts[0], parts[1]
                try:
                    lat_f, lon_f = float(parts[0]), float(parts[1])
                except ValueError:
                    lat_f = lon_f = None

        # Оценка полноты данных (без записи в seed)
        result = assess_resort(name, region, settlement, lat_f, lon_f)
        print_assessment(result)
        if result["chosen"] is None or not result["region_in_rosstat"]:
            raise SystemExit("Нельзя добавить: нет координаты или региона в Росстате")
        answer = input("Добавить? [y/n]: ").strip().lower()
        if answer != "y":
            raise SystemExit("Отменено — ничего не добавлено")

        if lat_s and set_resort_anchor(name, lat_s, lon_s):
            print(f"Обновлён seed-якорь (lat/lon) курорта: {name}", flush=True)
        else:
            append_resort_to_seed(name, region, settlement, lat_s, lon_s)
            print(f"Добавлен в seed: {name} ({region})", flush=True)

    if args.mode == "remove":
        if not (PROJECT_ROOT / "data" / "collected" / "coordinates_verified.json").exists():
            raise SystemExit(
                "Нет data/collected/coordinates_verified.json. "
                "Сначала запустите: python run_pipeline.py --mode full"
            )
        query = args.name.strip() if args.name else ""
        if not query:
            try:
                query = input("Название или resort_id курорта для удаления: ").strip()
            except EOFError:
                query = ""
        if not query:
            raise SystemExit("Не указан курорт для удаления")
        header, rows = _load_seed()
        found = _find_resort(rows, query)
        if found is None:
            raise SystemExit(f"Курорт не найден в data/raw/resort_seed.csv: {query}")
        index, row = found
        rid = f"R{index + 1:03d}"
        print(f"Найден курорт: {row.get('name_ru')} ({row.get('region')}) — resort_id {rid}", flush=True)
        try:
            answer = input("Вы уверены, что хотите удалить этот курорт? [y/N]: ").strip().lower()
        except EOFError:
            answer = ""
        if answer != "y":
            raise SystemExit("Отменено — курорт не удалён")
        removed_rid, removed_name = _remove_resort(header, rows, index)
        print(f"Удалён из seed и кэша: {removed_name} ({removed_rid})", flush=True)

    if args.mode in NEEDS_PREPARED and not (PROJECT_ROOT / "data" / "prepared" / "resorts.json").exists():
        raise SystemExit(
            "Нет data/prepared/resorts.json. Сначала запустите: python run_pipeline.py --mode full или --mode static"
        )

    steps = MODES[args.mode]
    if args.no_load:
        steps = [s for s in steps if s[0] != LOAD[0]]
    if args.force:
        # Принудительно пересобрать статические данные (геокодинг + OSM).
        steps = [
            tuple(list(s) + ["--force"]) if (s[0] in OVERPASS_SCRIPTS and "--force" not in s) else s
            for s in steps
        ]
    if args.mode == "rescore":
        _assert_no_network_steps(steps)
    print(f"Режим: {args.mode} — {len(steps)} шагов:")
    for i, step in enumerate(steps, 1):
        print(f"  {i}. {' '.join(step)}")

    # Pre-flight: ветка трогает Overpass (геокодинг/пересбор OSM) — проверяем доступность,
    # чтобы не собирать мусорные координаты/инфраструктуру при лежащих зеркалах.
    overpass_needed = any(
        s[0] in OVERPASS_SCRIPTS and "--only-climate" not in s for s in steps
    )
    if overpass_needed and not args.skip_overpass_check:
        print("\nPre-flight: проверка доступности Overpass ...", flush=True)
        alive, status = check_overpass()
        print("\n".join(status), flush=True)
        if alive == 0:
            if not _confirm_overpass_down():
                print("Пайплайн отменен пользователем.", flush=True)
                raise SystemExit(0)
        else:
            print(f"Overpass доступен: {alive}/{len(OVERPASS_ENDPOINTS)} зеркал.", flush=True)

    for script, *args_ in steps:
        run_step(script, *args_)

    print("\nПайплайн завершён успешно.")


if __name__ == "__main__":
    main()
