#!/usr/bin/env python3
"""Пересчёт курортных данных по улучшенным координатам.

Показатели, зависящие от координаты, в data/prepared/resorts.json остались от
эталонного сбора (по старым точкам). Этот скрипт пересобирает их по новым
координатам:

  * OSM-инфраструктура в радиусе 6 км (Overpass);
  * сложность и типы трасс (Overpass, теги piste:difficulty / piste:type);
  * климат (Open-Meteo Historical, ноябрь–апрель);
  * ближайший аэропорт (OurAirports).

Обновляет data/prepared/resorts.json и пишет data/mart/climate_monthly.csv.
Исходные raw-файлы не изменяются.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PREPARED_DIR = PROJECT_ROOT / "data" / "prepared"
MART = PROJECT_ROOT / "data" / "mart"
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
AIRPORTS_CACHE = CACHE_DIR / "airports.csv"
CLIMATE_CACHE = CACHE_DIR / "climate_daily.json"

sys.path.insert(0, str(PROJECT_ROOT))

from src.collect.openskimap_client import OpenSkiMapClient, OpenSkiMapError  # noqa: E402

OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
# (endpoint, verify_ssl): у maps.mail.ru самоподписанный сертификат — проверку отключаем.
OVERPASS_ENDPOINTS = [
    ("https://overpass-api.de/api/interpreter", True),
    ("https://overpass.kumi.systems/api/interpreter", True),
    ("https://maps.mail.ru/osm/tools/overpass/api/interpreter", False),
]
OURAIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
USER_AGENT = "TravelDesignerStudentWorkshop/1.0 open-data-research"

# Горизонт исторического климата: число зимних сезонов (ноябрь–апрель).
# 30 → сезоны 1996/97 … 2025/26 (ERA5 доступен с 1940 года).
WEATHER_YEARS = 30
WEATHER_END = "2026-04-30"
WINTER_MONTHS = {11, 12, 1, 2, 3, 4}
MONTH_NAMES_RU = {1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 11: "Ноябрь", 12: "Декабрь"}


def build_seasons(years: int, end: str) -> list[tuple[str, str]]:
    """Зимние сезоны (ноябрь–апрель) за `years` лет назад от `end`, в хронологическом порядке."""
    end_year = int(end[:4])
    return [
        (f"{end_year - offset}-11-01", f"{end_year - offset + 1}-04-30")
        for offset in range(years, 0, -1)
    ]

OSM_METRICS = [
    ("piste_segments_6km", "way", '["piste:type"="downhill"]'),
    (
        "lift_lines_6km",
        "way",
        '["aerialway"~"cable_car|gondola|chair_lift|drag_lift|t-bar|j-bar|platter|magic_carpet|rope_tow|mixed_lift"]',
    ),
    ("lodging_objects_6km", "nwr", '["tourism"~"hotel|hostel|guest_house|chalet|apartment"]'),
    ("food_objects_6km", "nwr", '["amenity"~"restaurant|cafe|fast_food|bar|food_court"]'),
    ("transport_objects_6km", "nwr", '["public_transport"~"station|platform|stop_position"]'),
    ("attraction_objects_6km", "nwr", '["tourism"~"attraction|viewpoint|museum|theme_park"]'),
]

# Сложность трасс (piste:difficulty) — стандартный набор значений OSM.
PISTE_DIFFICULTY_LEVELS = ["novice", "easy", "intermediate", "advanced", "expert", "freeride", "extreme"]

# Не-downhill типы трасс, которые храним отдельно; остальные попадают в "other".
PISTE_TYPES = ["nordic", "skitour", "snow_park", "sled"]

PISTE_RADIUS_M = 6000


def haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def request_json(url, *, params=None, data=None, throttle=0.6, attempts=4, timeout=180, verify_ssl=True):
    if params:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{urllib.parse.urlencode(params)}"
    time.sleep(throttle)
    headers = {"User-Agent": USER_AGENT}
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    context = None
    if not verify_ssl:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    last = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 503, 504) and attempt < attempts:
                wait = 0.0
                if e.headers and e.headers.get("Retry-After"):
                    wait = float(e.headers.get("Retry-After"))
                time.sleep(max(wait, 10 * attempt))  # 10, 20, 30, … сек (защита от 429)
                continue
            raise
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            # Ответ не распарсился (rate-limit HTML / обрыв) — повторяем.
            last = e
            if attempt < attempts:
                time.sleep(2.0 * attempt)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if attempt < attempts:
                time.sleep(1.5 * attempt)
                continue
            raise
    raise RuntimeError(f"request failed: {url}: {last}")


def _overpass_query(query: str, *, throttle: float = 2.5, timeout: int = 180) -> dict[str, Any]:
    """Overpass-запрос с перебором зеркал при перегрузке/таймауте."""
    last_error: Exception | None = None
    for endpoint, verify_ssl in OVERPASS_ENDPOINTS:
        try:
            return request_json(
                endpoint, data={"data": query}, throttle=throttle,
                attempts=4, timeout=timeout, verify_ssl=verify_ssl,
            )
        except Exception as exc:  # noqa: BLE001 — пробуем следующее зеркало
            last_error = exc
    raise RuntimeError(f"Overpass недоступен на всех зеркалах: {last_error}")


def load_resorts() -> list[dict[str, Any]]:
    return json.loads((PREPARED_DIR / "resorts.json").read_text(encoding="utf-8"))


def save_resorts(resorts: list[dict[str, Any]]) -> None:
    (PREPARED_DIR / "resorts.json").write_text(
        json.dumps(resorts, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def ski_season(date_value: str) -> str:
    year = int(date_value[:4])
    month = int(date_value[5:7])
    return f"{year}-{str(year + 1)[-2:]}" if month >= 11 else f"{year - 1}-{str(year)[-2:]}"


def collect_openskimap(resorts: list[dict[str, Any]], force: bool = False) -> None:
    """Приоритетный источник: заполнить статистику трасс/подъёмников из OpenSkiMap.

    Для каждого курорта ищем skiArea по названию. Если найден — берём статистику
    (piste_difficulty_*, lift_lines_6km, высоты, длину трасс) и метаданные
    (openskimap_id/name/websites/sources). Если не найден или ошибка сети —
    оставляем поля как есть (None), Overpass остаётся fallback.

    Инкрементально: курорты с уже найденным openskimap_id пропускаются (если не force).
    """
    client = OpenSkiMapClient()
    for resort in resorts:
        if not force and resort.get("openskimap_id"):
            continue
        name = resort["name_ru"]
        try:
            areas = client.search_resort(name)
        except OpenSkiMapError as exc:
            print(f"  [openskimap] {resort['resort_id']} {name}: {type(exc).__name__}", flush=True)
            continue
        if not areas:
            continue
        area = areas[0]
        props = area.get("properties", {}) or {}
        resort.update(OpenSkiMapClient.map_statistics(area))
        resort["openskimap_id"] = props.get("id")
        resort["openskimap_name"] = props.get("name")
        resort["official_website_url"] = "; ".join(props.get("websites") or []) or None
        resort["openskimap_sources"] = "; ".join(
            f"{s.get('type')}:{s.get('id')}" for s in (props.get("sources") or [])
        ) or None
    found = sum(1 for r in resorts if r.get("openskimap_id"))
    print(f"OpenSkiMap: заполнено {found}/{len(resorts)} курортов", flush=True)


def collect_osm(resorts: list[dict[str, Any]], force: bool = False) -> None:
    """Пересчитать OSM-инфраструктуру по новым координатам (радиус 6 км).

    OpenSkiMap — приоритетный источник для трасс/подъёмников: для курортов с
    openskimap_id поля piste_segments_6km/lift_lines_6km не запрашиваем, но
    amenities (размещение/питание/транспорт/достопримечательности) собираем всегда.
    """
    todo = [
        r for r in resorts
        if force or any(r.get(m) is None for m, _, _ in OSM_METRICS)
    ]
    print(f"OSM: инфраструктура ({len(todo)} запросить, {len(resorts) - len(todo)} пропустить) ...", flush=True)
    for start in range(0, len(todo), 2):
        batch = todo[start : start + 2]
        lines = ["[out:json][timeout:120];"]
        for ri, resort in enumerate(batch):
            skip_piste_lift = bool(resort.get("openskimap_id"))
            for mi, (metric, el_type, osm_filter) in enumerate(OSM_METRICS):
                if skip_piste_lift and metric in ("piste_segments_6km", "lift_lines_6km"):
                    continue  # OpenSkiMap уже заполнил — Overpass не нужен
                set_name = f"s{ri}_{mi}"
                lines.append(
                    f"{el_type}(around:6000,{resort['latitude']},{resort['longitude']})"
                    f"{osm_filter}->.{set_name};"
                )
                count = (
                    f"{set_name}.count(ways)"
                    if el_type == "way"
                    else f"{set_name}.count(nodes)+{set_name}.count(ways)+{set_name}.count(relations)"
                )
                lines.append(
                    f'make stats resort_id="{resort["resort_id"]}",'
                    f'metric="{metric}",value={count};out;'
                )
        query = "\n".join(lines)
        try:
            payload = _overpass_query(query)
        except Exception as exc:  # noqa: BLE001
            print(f"  OSM batch {start} failed: {type(exc).__name__}", flush=True)
            continue
        by_id = {r["resort_id"]: r for r in batch}
        for el in payload.get("elements", []):
            tags = el.get("tags", {})
            resort = by_id.get(tags.get("resort_id"))
            metric = tags.get("metric")
            if resort is not None and metric:
                try:
                    resort[metric] = int(float(tags.get("value")))
                except (TypeError, ValueError):
                    resort[metric] = None
        for r in batch:
            r["osm_radius_km"] = 6
            r["osm_data_timestamp"] = payload.get("osm3s", {}).get("timestamp_osm_base", "")
        print(f"  OSM {min(start + 2, len(todo))}/{len(todo)}", flush=True)
        time.sleep(2)


def parse_piste_elements(elements: list[dict[str, Any]]) -> dict[str, Any]:
    """Разложить Overpass-элементы (way с piste:type) на сложность и типы трасс.

    Сложность (piste:difficulty) считается только по downhill-трассам: именно они
    релевантны для категоризации райдеров. Возвращает словарь полей, которые
    присоединяются прямо к курорту (без отдельной витрины).
    """
    difficulty = {level: 0 for level in PISTE_DIFFICULTY_LEVELS}
    unknown = 0
    downhill = 0
    type_counts: dict[str, int] = defaultdict(int)

    for el in elements:
        tags = el.get("tags", {})
        ptype = tags.get("piste:type", "")
        type_counts[ptype or "(none)"] += 1
        if ptype == "downhill":
            downhill += 1
            diff = tags.get("piste:difficulty", "")
            if diff in difficulty:
                difficulty[diff] += 1
            elif diff:
                # нестандартное значение сложности (редко) — в extreme
                difficulty["extreme"] += 1
            else:
                unknown += 1

    total = len(elements)
    listed = sum(type_counts.get(t, 0) for t in PISTE_TYPES)
    with_difficulty = downhill - unknown
    return {
        "piste_ways_total": total,
        "piste_difficulty_novice": difficulty["novice"],
        "piste_difficulty_easy": difficulty["easy"],
        "piste_difficulty_intermediate": difficulty["intermediate"],
        "piste_difficulty_advanced": difficulty["advanced"],
        "piste_difficulty_expert": difficulty["expert"],
        "piste_difficulty_freeride": difficulty["freeride"],
        "piste_difficulty_extreme": difficulty["extreme"],
        "piste_difficulty_unknown": unknown,
        "piste_type_nordic": type_counts.get("nordic", 0),
        "piste_type_skitour": type_counts.get("skitour", 0),
        "piste_type_snow_park": type_counts.get("snow_park", 0),
        "piste_type_sled": type_counts.get("sled", 0),
        "piste_type_other": max(total - downhill - listed, 0),
        "piste_difficulty_coverage": round(with_difficulty / downhill, 4) if downhill else None,
    }


def collect_piste_tags(resorts: list[dict[str, Any]], force: bool = False) -> None:
    """Сложность и типы трасс из OSM (piste:difficulty / piste:type), радиус 6 км.

    Один запрос Overpass на курорт (out tags), результат присоединяется к курорту.
    Инкрементально: курорты с уже собранными данными пропускаются (если не force).
    """
    todo = [
        r for r in resorts
        if not r.get("openskimap_id") and (force or "piste_ways_total" not in r)
    ]
    print(f"OSM: сложность и типы трасс ({len(todo)} запросить, {len(resorts) - len(todo)} пропустить) ...", flush=True)
    for i, resort in enumerate(todo, start=1):
        print(f"  piste [{i}/{len(todo)}] {resort['resort_id']} {resort['name_ru']}", flush=True)
        query = (
            "[out:json][timeout:120];\n"
            f"way(around:{PISTE_RADIUS_M},{resort['latitude']},{resort['longitude']})[\"piste:type\"];\n"
            "out tags;"
        )
        try:
            payload = _overpass_query(query)
        except Exception as exc:  # noqa: BLE001
            print(f"  piste {resort['resort_id']} failed: {type(exc).__name__}", flush=True)
            continue
        resort.update(parse_piste_elements(payload.get("elements", [])))
        resort["piste_data_timestamp"] = payload.get("osm3s", {}).get("timestamp_osm_base", "")


def collect_airport(resorts: list[dict[str, Any]], force: bool = False) -> None:
    """Пересчитать ближайший аэропорт по координатам (OurAirports, с кэшированием).

    Справочник airports.csv — тяжёлый статичный файл, поэтому кэшируется в
    data/cache/airports.csv:
      * --force      → скачать заново и перезаписать кэш;
      * без --force  → читать из локального кэша (без сети), если он есть;
      * кэша нет и сеть недоступна → предупреждение и пропуск шага (без зависания).
    """
    text = _load_airports_text(force)
    if text is None:
        print(
            "ВНИМАНИЕ: Не удалось скачать справочник аэропортов. "
            "Расстояния не будут рассчитаны.",
            flush=True,
        )
        return
    airports = [
        row
        for row in csv.DictReader(io.StringIO(text))
        if row["iso_country"] == "RU"
        and row["scheduled_service"] == "yes"
        and row["iata_code"]
        and row["type"] in {"large_airport", "medium_airport"}
    ]
    if not airports:
        print(
            "ВНИМАНИЕ: в справочнике аэропортов нет подходящих записей. "
            "Расстояния не будут рассчитаны.",
            flush=True,
        )
        return
    for resort in resorts:
        nearest = min(
            airports,
            key=lambda a: haversine_km(
                resort["latitude"], resort["longitude"],
                float(a["latitude_deg"]), float(a["longitude_deg"]),
            ),
        )
        resort["nearest_scheduled_airport"] = nearest["name"]
        resort["nearest_airport_iata"] = nearest["iata_code"]
        resort["nearest_airport_distance_km"] = round(
            haversine_km(
                resort["latitude"], resort["longitude"],
                float(nearest["latitude_deg"]), float(nearest["longitude_deg"]),
            ), 1,
        )
        resort["nearest_airport_municipality"] = nearest["municipality"]
    print("  Аэропорты пересчитаны", flush=True)


def _load_airports_text(force: bool) -> str | None:
    """Вернуть текст справочника аэропортов (из кэша или скачав и сохранив в кэш)."""
    if not force and AIRPORTS_CACHE.exists():
        print("  [airport] читаю из кэша (data/cache/airports.csv)", flush=True)
        return AIRPORTS_CACHE.read_text(encoding="utf-8")

    print("  [airport] скачиваю справочник (разово, дальше из кэша) ...", flush=True)
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(OURAIRPORTS_URL, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp:
                text = resp.read().decode("utf-8")
            AIRPORTS_CACHE.parent.mkdir(parents=True, exist_ok=True)
            AIRPORTS_CACHE.write_text(text, encoding="utf-8")
            print(f"  [airport] справочник сохранён в кэш: {AIRPORTS_CACHE}", flush=True)
            return text
        except Exception as exc:  # noqa: BLE001 — сеть/таймаут
            print(f"  [airport] попытка {attempt}: {type(exc).__name__}", flush=True)
            time.sleep(2 * attempt)
    return None


def _safe_mean(values) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _load_climate_cache() -> dict[str, list[dict[str, Any]]]:
    if CLIMATE_CACHE.exists():
        try:
            return json.loads(CLIMATE_CACHE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_climate_cache(cache: dict[str, list[dict[str, Any]]]) -> None:
    CLIMATE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CLIMATE_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def _collected_seasons(cache: dict[str, list[dict[str, Any]]], rid: str) -> set[str]:
    return {row["season"] for row in cache.get(rid, [])}


def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _climate_elevation(resort: dict[str, Any]) -> float | None:
    """Высота для запроса климата: средняя высота склона (OpenSkiMap), иначе точка Open-Meteo."""
    lo = resort.get("piste_min_elevation_m")
    hi = resort.get("piste_max_elevation_m")
    if lo is not None and hi is not None:
        return (float(lo) + float(hi)) / 2
    return resort.get("open_meteo_elevation_m")


def collect_climate(resorts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Пересчитать климат (посезонно, инкрементально, ноябрь–апрель)."""
    print("Климат: загрузка исторических данных (инкрементально) ...", flush=True)
    cache = _load_climate_cache()
    seasons = build_seasons(WEATHER_YEARS, WEATHER_END)
    daily_vars = (
        "temperature_2m_mean,temperature_2m_min,temperature_2m_max,"
        "precipitation_sum,snowfall_sum"
    )

    for start in range(0, len(resorts), 16):
        batch = resorts[start : start + 16]
        for resort in batch:
            if len(_collected_seasons(cache, resort["resort_id"])) >= len(seasons):
                print(f"  [climate] {resort['resort_id']}: уже собрано {len(seasons)} сезонов, пропуск", flush=True)

        for s_start, s_end in seasons:
            season_id = ski_season(s_start)
            need = [r for r in batch if season_id not in _collected_seasons(cache, r["resort_id"])]
            if not need:
                continue
            try:
                elevs = [_climate_elevation(r) for r in need]
                params = {
                    "latitude": ",".join(str(r["latitude"]) for r in need),
                    "longitude": ",".join(str(r["longitude"]) for r in need),
                    "elevation": ",".join("nan" if e is None else str(e) for e in elevs),
                    "start_date": s_start,
                    "end_date": s_end,
                    "daily": daily_vars,
                    "timezone": "auto",
                    "models": "era5",
                }
                payload = request_json(
                    OPEN_METEO_ARCHIVE, params=params, throttle=2.0, attempts=3, timeout=120
                )
                payloads = payload if isinstance(payload, list) else [payload]
                for resort, item in zip(need, payloads):
                    resort.setdefault("open_meteo_elevation_m", item.get("elevation"))
                    daily = item.get("daily", {})
                    for i, date in enumerate(daily.get("time", [])):
                        cache.setdefault(resort["resort_id"], []).append(
                            {
                                "date": date,
                                "season": ski_season(date),
                                "month": int(date[5:7]),
                                "temp": _at(daily, "temperature_2m_mean", i),
                                "precip": _at(daily, "precipitation_sum", i),
                                "snowfall": _at(daily, "snowfall_sum", i),
                            }
                        )
                print(f"  [climate] {season_id} скачан ({len(need)} кур.) {_now_ts()}", flush=True)
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    _save_climate_cache(cache)
                    print(f"  [climate] лимит достигнут в {_now_ts()}", flush=True)
                    print(
                        "[climate] Достигнут дневной лимит Open-Meteo. "
                        "Докачка остановлена. Ожидайте сброса лимита (~1 час).",
                        flush=True,
                    )
                    sys.exit(1)
                print(f"  Климат сезон {s_start} не удался: HTTPError {exc.code}", flush=True)
            except Exception as exc:  # noqa: BLE001 — пропускаем сезон, продолжаем
                print(f"  Климат сезон {s_start} не удался: {type(exc).__name__}", flush=True)
            time.sleep(5)

        print(f"  Климат {min(start + 16, len(resorts))}/{len(resorts)}", flush=True)
        _save_climate_cache(cache)  # сохраняем после каждого батча (устойчивость)

    monthly_rows = _compute_climate(resorts, cache, seasons)
    _save_climate_cache(cache)
    return monthly_rows


def _compute_climate(
    resorts: list[dict[str, Any]],
    cache: dict[str, list[dict[str, Any]]],
    seasons: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    monthly_rows: list[dict[str, Any]] = []
    for resort in resorts:
        rows = cache.get(resort["resort_id"], [])

        season_ids = sorted({r["season"] for r in rows})
        season_snow = [sum(r["snowfall"] or 0 for r in rows if r["season"] == s) for s in season_ids]
        season_freeze = [
            sum(1 for r in rows if r["season"] == s and r["temp"] is not None and r["temp"] < 0)
            for s in season_ids
        ]
        season_snow_days = [
            sum(1 for r in rows if r["season"] == s and r["snowfall"] is not None and r["snowfall"] >= 0.1)
            for s in season_ids
        ]

        resort["winter_mean_temperature_c"] = _safe_mean(r["temp"] for r in rows)
        resort["avg_snowfall_cm_per_season"] = _safe_mean(season_snow)
        resort["avg_freezing_days_per_season"] = _safe_mean(season_freeze)
        resort["avg_snow_days_per_season"] = _safe_mean(season_snow_days)
        snowfalls = [r["snowfall"] for r in rows if r["snowfall"] is not None]
        resort["max_daily_snowfall_cm"] = max(snowfalls) if snowfalls else None
        resort["weather_model"] = "ERA5"
        resort["weather_period_start"] = seasons[0][0]
        resort["weather_period_end"] = WEATHER_END
        resort["climate_elevation_m"] = _climate_elevation(resort)

        for month in (11, 12, 1, 2, 3, 4):
            mrows = [r for r in rows if r["month"] == month]
            years = sorted({r["date"][:4] for r in mrows})
            groups = [[r for r in mrows if r["date"].startswith(y)] for y in years]
            monthly_rows.append(
                {
                    "resort_id": resort["resort_id"],
                    "name_ru": resort["name_ru"],
                    "region": resort["region"],
                    "month": month,
                    "month_name_ru": MONTH_NAMES_RU[month],
                    "years_count": len(years),
                    "mean_temperature_c": _safe_mean(r["temp"] for r in mrows),
                    "avg_monthly_precipitation_mm": _safe_mean(
                        sum(r["precip"] or 0 for r in g) for g in groups
                    ),
                    "avg_monthly_snowfall_cm": _safe_mean(
                        sum(r["snowfall"] or 0 for r in g) for g in groups
                    ),
                    "avg_freezing_days": _safe_mean(
                        sum(1 for r in g if r["temp"] is not None and r["temp"] < 0) for g in groups
                    ),
                    "avg_snow_days": _safe_mean(
                        sum(1 for r in g if r["snowfall"] is not None and r["snowfall"] >= 0.1)
                        for g in groups
                    ),
                    "weather_model": "ERA5",
                }
            )
    return monthly_rows


def _at(daily: dict, field: str, index: int) -> float | None:
    values = daily.get(field) or []
    return values[index] if index < len(values) else None


def compute_osm_overlap(resorts: list[dict[str, Any]]) -> None:
    """Пересчитать osm_overlap_warning по новым координатам (соседи < 12 км)."""
    for resort in resorts:
        neighbors = []
        for other in resorts:
            if other["resort_id"] == resort["resort_id"]:
                continue
            distance = haversine_km(
                resort["latitude"], resort["longitude"],
                other["latitude"], other["longitude"],
            )
            if distance < 12:
                neighbors.append((distance, other["name_ru"]))
        neighbors.sort()
        resort["osm_overlap_warning"] = (
            "Possible overlap with "
            + ", ".join(f"{name} ({distance:.1f} km)" for distance, name in neighbors)
            if neighbors
            else ""
        )


def compute_quality_fields(resorts: list[dict[str, Any]]) -> None:
    """Пересчитать completeness_pct и quality_flags по фактическим данным."""
    for resort in resorts:
        required = [
            resort.get("latitude"),
            resort.get("longitude"),
            resort.get("coordinate_source_url"),
            resort.get("piste_segments_6km"),
            resort.get("lift_lines_6km"),
            resort.get("lodging_objects_6km"),
            resort.get("food_objects_6km"),
            resort.get("open_meteo_elevation_m"),
            resort.get("winter_mean_temperature_c"),
            resort.get("avg_snowfall_cm_per_season"),
            resort.get("nearest_airport_distance_km"),
        ]
        resort["completeness_pct"] = sum(
            value not in (None, "") for value in required
        ) / len(required)

        flags = []
        if resort.get("coordinate_status") == "needs_review":
            flags.append("check coordinates")
        if resort.get("osm_overlap_warning"):
            flags.append("OSM radii overlap")
        if any(key.endswith("_error") and value for key, value in resort.items()):
            flags.append("source error")
        if not resort.get("openskimap_id"):
            # Курорт не найден в OpenSkiMap — статистика трасс/подъёмников отсутствует.
            flags.append("missing_openskimap_data")
        resort["quality_flags"] = "; ".join(flags) or None


def _collect_and_save_climate(resorts: list[dict[str, Any]]) -> None:
    """Собрать климат (Open-Meteo Archive) и записать resort-поля + climate_monthly.csv."""
    monthly = collect_climate(resorts)
    save_resorts(resorts)
    header = [
        "resort_id", "name_ru", "region", "month", "month_name_ru", "years_count",
        "mean_temperature_c", "avg_monthly_precipitation_mm", "avg_monthly_snowfall_cm",
        "avg_freezing_days", "avg_snow_days", "weather_model",
    ]
    matrix = [header] + [[r.get(c) for c in header] for r in monthly]
    with open(MART / "climate_monthly.csv", "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(matrix)
    print("  -> климат сохранён", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quality-only", action="store_true",
        help="пересчитать только производные поля качества (osm_overlap, completeness, quality_flags)",
    )
    parser.add_argument(
        "--piste-only", action="store_true",
        help="пересчитать только сложность и типы трасс (piste:difficulty / piste:type)",
    )
    parser.add_argument(
        "--only-climate", action="store_true",
        help="собрать только климат (Open-Meteo Archive), пропуская OpenSkiMap/OSM/аэропорты",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="пересобрать заново, не пропуская уже собранные статичные данные (OSM/трассы)",
    )
    args = parser.parse_args()

    resorts = load_resorts()
    print(f"Пересчёт курортных данных для {len(resorts)} курортов", flush=True)
    collected_at = datetime.now(UTC).isoformat()
    for r in resorts:
        r["data_recomputed_at"] = collected_at

    if args.quality_only:
        compute_osm_overlap(resorts)
        compute_quality_fields(resorts)
        save_resorts(resorts)
        print("Готово: поля качества пересчитаны", flush=True)
        return

    if args.piste_only:
        collect_openskimap(resorts, force=args.force)
        collect_piste_tags(resorts, force=args.force)
        save_resorts(resorts)
        print("Готово: сложность и типы трасс обновлены", flush=True)
        return

    if args.only_climate:
        _collect_and_save_climate(resorts)
        print("Готово: климат обновлён (only-climate)", flush=True)
        return

    collect_openskimap(resorts, force=args.force)
    save_resorts(resorts)
    print("  -> OpenSkiMap сохранён", flush=True)

    collect_osm(resorts, force=args.force)
    save_resorts(resorts)
    print("  -> OSM сохранено", flush=True)

    collect_piste_tags(resorts, force=args.force)
    save_resorts(resorts)
    print("  -> сложность и типы трасс сохранены", flush=True)

    _collect_and_save_climate(resorts)

    collect_airport(resorts, force=args.force)
    compute_osm_overlap(resorts)
    compute_quality_fields(resorts)
    save_resorts(resorts)
    print("  -> аэропорты + качество сохранены", flush=True)

    print("Готово: resorts.json и climate_monthly.json обновлены", flush=True)


if __name__ == "__main__":
    main()
