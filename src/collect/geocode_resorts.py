#!/usr/bin/env python3
"""Геокодинг курортов по названию (цепочка: OpenSkiMap → Wikidata → Overpass).

Читает seed data/raw/resort_seed.csv (name_ru + region + settlement) и собирает
координаты: основной источник — OpenSkiMap (готовые координаты skiArea), затем
Wikidata (P625 по Q-id из поиска по имени), затем центроид OSM-объектов катания
(Overpass) вокруг ориентира заказчика.

Результат: data/collected/coordinates_verified.json (seed не изменяется).

Запуск:
    python src/collect/geocode_resorts.py            # все курорты из seed
    python src/collect/geocode_resorts.py --limit 5  # первые 5 (проверка)
    python src/collect/geocode_resorts.py --resort R001,R032
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.transform.regions import region_key  # noqa: E402
from src.collect.openskimap_client import OpenSkiMapClient, OpenSkiMapError  # noqa: E402

RAW_DIR = PROJECT_ROOT / "data" / "raw"
SEED_CSV = RAW_DIR / "resort_seed.csv"
OUTPUT_DIR = PROJECT_ROOT / "data" / "collected"
DEFAULT_OUTPUT = OUTPUT_DIR / "coordinates_verified.json"

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_ENTITY = "https://www.wikidata.org/wiki/Special:EntityData"
# (endpoint, verify_ssl): у maps.mail.ru самоподписанный сертификат — проверку отключаем.
OVERPASS_ENDPOINTS = [
    ("https://overpass-api.de/api/interpreter", True),
    ("https://overpass.kumi.systems/api/interpreter", True),
    ("https://maps.mail.ru/osm/tools/overpass/api/interpreter", False),
]
NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"

USER_AGENT = "TravelDesignerStudentWorkshop/1.0 open-data-research"

# Пауза между запросами к источнику (сек) — вежливость к публичным API.
THROTTLE = {"wikidata": 0.6, "overpass": 2.5}

# Приоритет источника при выборе итоговой точки (выше = надёжнее).
# OpenSkiMap — основной источник (готовые координаты skiArea).
SOURCE_PRIORITY = {"openskimap": 5, "osm_centroid": 4, "wikidata": 3}

# Качества координат, считаемые подтверждёнными: при инкрементальном прогоне их не
# перегеокодируем (только --force пересматривает всё заново).
KEEP_QUALITIES = {"exact", "osm_centroid", "openskimap"}

SKI_RE = re.compile(r"горнолыж|курорт|комплекс|фанпарк|сноуборд|лыжн|ski|snow")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=0, help="Обработать только первые N курортов")
    parser.add_argument("--resort", type=str, default="", help="Список resort_id через запятую")
    parser.add_argument("--force", action="store_true", help="перегеокодировать все курорты (игнорировать skip exact/osm_centroid)")
    return parser.parse_args()


def load_resorts() -> list[dict[str, Any]]:
    """Справочник курортов из seed (name_ru + region + нас.пункт + опц. координаты)."""
    resorts: list[dict[str, Any]] = []
    with open(SEED_CSV, encoding="utf-8-sig", newline="") as file:
        for index, row in enumerate(csv.DictReader(file), start=1):
            lat = (row.get("lat") or "").strip()
            lon = (row.get("lon") or "").strip()
            resorts.append({
                "resort_id": f"R{index:03d}",
                "name_ru": row["name_ru"].strip(),
                "region": row["region"].strip(),
                "settlement": (row.get("settlement") or "").strip(),
                "latitude": float(lat) if lat else None,
                "longitude": float(lon) if lon else None,
            })
    return resorts


def load_reference_coords() -> dict[str, dict[str, Any]]:
    """Координаты-ориентиры заказчика (Приложение В) из data/raw/resorts.json.

    Используются только как fallback: если автоопределение по трём точкам
    (название + регион + нас.пункт) не дало координату, берём ориентир.
    """
    matrix = json.loads((RAW_DIR / "resorts.json").read_text(encoding="utf-8"))
    header, rows = matrix[0], matrix[1:]
    refs: dict[str, dict[str, Any]] = {}
    for row in rows:
        r = dict(zip(header, row))
        refs[r["resort_id"]] = {
            "latitude": float(r["latitude"]),
            "longitude": float(r["longitude"]),
            "quality": r.get("coordinate_quality", ""),
        }
    return refs


def load_previous_coords(path: Path) -> dict[str, dict[str, Any]]:
    """Прочитать прошлый coordinates_verified.json → {resort_id: результат}."""
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {r["resort_id"]: r for r in payload.get("resorts", [])}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", " ", text, flags=re.IGNORECASE).strip()


def request_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    throttle: float = 0.6,
    attempts: int = 4,
    timeout: int = 60,
    verify_ssl: bool = True,
) -> Any:
    """GET/POST JSON с троттлингом, backoff и учётом Retry-After."""
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
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code in (429, 500, 503, 504) and attempt < attempts:
                wait = 0.0
                if error.headers and error.headers.get("Retry-After"):
                    wait = float(error.headers.get("Retry-After"))
                time.sleep(max(wait, 2 ** attempt))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt < attempts:
                time.sleep(1.5 * attempt)
                continue
            raise
    raise RuntimeError(f"request failed: {url}: {last_error}")


def wikidata_coord(qid: str) -> dict[str, Any] | None:
    """Получить координаты P625 элемента Wikidata по Q-id."""
    if not qid:
        return None
    payload = request_json(f"{WIKIDATA_ENTITY}/{qid}.json", throttle=THROTTLE["wikidata"])
    entity = payload.get("entities", {}).get(qid, {})
    p625 = entity.get("claims", {}).get("P625")
    if not p625:
        return None
    try:
        value = p625[0]["mainsnak"]["datavalue"]["value"]
        labels = entity.get("labels", {})
        label = labels.get("ru", {}).get("value") or labels.get("en", {}).get("value", qid)
        return {
            "source": "wikidata",
            "latitude": float(value["latitude"]),
            "longitude": float(value["longitude"]),
            "title": label,
            "qid": qid,
        }
    except (KeyError, TypeError, ValueError):
        return None


def wikidata_search(name: str, settlement: str = "") -> str:
    """Найти Q-id курорта по названию через wbsearchentities."""
    payload = request_json(
        WIKIDATA_API,
        params={
            "action": "wbsearchentities",
            "search": f"{name} {settlement}".strip(),
            "language": "ru",
            "format": "json",
            "limit": 5,
        },
        throttle=THROTTLE["wikidata"],
    )
    tokens = {t for t in normalize(name).split() if len(t) >= 3}
    settlement_tokens = {t for t in normalize(settlement).split() if len(t) >= 3}
    best: tuple[int, str] | None = None
    for item in payload.get("search", []):
        label = normalize(item.get("label", ""))
        desc = normalize(item.get("description", ""))
        score = sum(2 for t in tokens if t in label)
        if SKI_RE.search(label) or SKI_RE.search(desc):
            score += 4
        if settlement_tokens and any(t in label or t in desc for t in settlement_tokens):
            score += 3
        if best is None or score > best[0]:
            best = (score, item["id"])
    if best and best[0] >= 1:
        return best[1]
    if payload.get("search"):
        return payload["search"][0]["id"]
    return ""


_OVERPASS_DOWN = False


def _overpass_query(query: str) -> dict[str, Any]:
    """Выполнить Overpass-запрос, перебирая зеркала при перегрузке."""
    global _OVERPASS_DOWN
    if _OVERPASS_DOWN:
        raise RuntimeError("Overpass недоступен (пропуск по circuit breaker)")
    last_error: Exception | None = None
    for endpoint, verify_ssl in OVERPASS_ENDPOINTS:
        try:
            return request_json(
                endpoint, data={"data": query}, throttle=THROTTLE["overpass"],
                attempts=2, timeout=15, verify_ssl=verify_ssl,
            )
        except Exception as exc:  # noqa: BLE001 — пробуем следующее зеркало
            last_error = exc
    _OVERPASS_DOWN = True
    raise RuntimeError(f"Overpass недоступен на всех зеркалах: {last_error}")


def _osm_centroid_at_radius(lat: float, lon: float, radius: int) -> dict[str, Any] | None:
    """Центроид объектов катания OSM в заданном радиусе (метры)."""
    query = f"""[out:json][timeout:15];
(
  node["aerialway"](around:{radius},{lat},{lon});
  way["piste:type"="downhill"](around:{radius},{lat},{lon});
);
out center;"""
    payload = _overpass_query(query)
    points: list[tuple[float, float]] = []
    for el in payload.get("elements", []):
        if el.get("type") == "node" and "lat" in el:
            points.append((el["lat"], el["lon"]))
        elif el.get("type") == "way" and el.get("center"):
            points.append((el["center"]["lat"], el["center"]["lon"]))
    if len(points) < 3:
        return None
    return {
        "source": "osm_centroid",
        "latitude": fmean(p[0] for p in points),
        "longitude": fmean(p[1] for p in points),
        "title": f"центроид OSM, r={radius // 1000}км ({len(points)} объектов)",
        "object_count": len(points),
        "radius_m": radius,
    }


def osm_ski_centroid(lat: float, lon: float) -> dict[str, Any] | None:
    """Центроид объектов катания: сначала 6 км, при нехватке — 15 км.

    Радиус 6 км совпадает с радиусом OSM-метрик рейтинга и не цепляет соседние
    курорты; 15 км нужен для курортов, чья текущая (proxy) координата сбита
    на несколько километров (посёлок/город).
    """
    for radius in (6000, 15000):
        result = _osm_centroid_at_radius(lat, lon, radius)
        if result:
            return result
    return None


def openskimap_coord(name: str) -> dict[str, Any] | None:
    """Координата skiArea из OpenSkiMap (прямой поиск GET /search).

    Возвращает кандидата {'source': 'openskimap', 'latitude', 'longitude',
    'title'} или None, если курорт не найден / ошибка сети.
    """
    try:
        client = OpenSkiMapClient()
        areas = client.search_resort(name)
    except OpenSkiMapError as exc:
        print(f"  [openskimap] {name}: {type(exc).__name__}", flush=True)
        return None
    if not areas:
        return None
    area = areas[0]
    coord = OpenSkiMapClient.extract_coordinate(area["geometry"])
    if coord is None:
        return None
    lon, lat = coord
    return {
        "source": "openskimap",
        "latitude": lat,
        "longitude": lon,
        "title": area["properties"].get("name", name),
    }


def gather_candidates(resort: dict[str, Any]) -> list[dict[str, Any]]:
    """Кандидаты координат: OpenSkiMap -> Wikidata -> Overpass.

    Простой прямой поиск: OpenSkiMap (GET /search) в приоритете. Если не найден —
    Wikidata (P625), затем Overpass-центроид вокруг ориентира заказчика. Прочие
    источники (Wikipedia/Nominatim) убраны как «мусорные».
    """
    name = resort["name_ru"]
    settlement = resort.get("settlement", "")
    candidates: list[dict[str, Any]] = []

    # 1) OpenSkiMap — прямой поиск.
    coord = openskimap_coord(name)
    if coord:
        candidates.append(coord)
        return candidates  # найден напрямую — останавливаемся

    # 2) Wikidata — поиск по названию, координата P625.
    try:
        coord = wikidata_coord(wikidata_search(name, settlement))
        if coord:
            candidates.append(coord)
    except Exception as exc:  # noqa: BLE001 — источник не критичен
        print(f"  [wikidata] {resort['resort_id']}: {type(exc).__name__}", flush=True)

    # 3) Overpass — центроид объектов катания вокруг ориентира заказчика.
    if not candidates:
        anchor = None
        if resort.get("latitude") is not None and resort.get("longitude") is not None:
            anchor = {"latitude": float(resort["latitude"]), "longitude": float(resort["longitude"])}
        if anchor is not None:
            try:
                coord = osm_ski_centroid(anchor["latitude"], anchor["longitude"])
                if coord:
                    candidates.append(coord)
            except Exception as exc:  # noqa: BLE001
                print(f"  [osm] {resort['resort_id']}: {type(exc).__name__}", flush=True)

    return candidates


def reverse_region(lat: float, lon: float) -> str | None:
    """Субъект РФ по координате через обратный геокодинг Nominatim."""
    params = urllib.parse.urlencode(
        {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 6}
    )
    url = f"{NOMINATIM_REVERSE}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("address", {}).get("state")


def select_coordinate(
    resort: dict[str, Any], candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    """Перекрёстно проверить кандидатов и выбрать лучшую точку.

    Кандидаты в другом регионе отбрасываются (регион из seed — «якорь»
    дисамбигации, заменяющий прежние «якорные» координаты).
    """
    region = resort.get("region", "")
    valid: list[dict[str, Any]] = []
    for c in candidates:
        if region:
            try:
                state = reverse_region(c["latitude"], c["longitude"])
                time.sleep(1.1)
                if state is not None and region_key(state) != region_key(region):
                    continue  # кандидат в другом регионе — отбрасываем
            except Exception:  # noqa: BLE001 — не смогли проверить регион, оставляем
                pass
        valid.append(c)

    if not valid:
        return {
            "chosen": None,
            "quality": "review",
            "reason": "нет кандидатов в регионе курорта",
        }

    # Первично — реальная точка курорта (OpenSkiMap/Wikidata).
    # OSM-центроид — это «центр зоны катания» (среднее трасс/подъёмников), а не
    # местоположение курорта, поэтому он используется только как fallback.
    osm = next((c for c in valid if c["source"] == "osm_centroid"), None)
    non_osm = [c for c in valid if c["source"] != "osm_centroid"]

    clusters: list[dict[str, Any]] = []
    for c in non_osm:
        for cl in clusters:
            if haversine_km(cl["lat"], cl["lon"], c["latitude"], c["longitude"]) <= 2.0:
                cl["members"].append(c)
                break
        else:
            clusters.append({"lat": c["latitude"], "lon": c["longitude"], "members": [c]})

    for cl in clusters:
        cl["lat"] = fmean(m["latitude"] for m in cl["members"])
        cl["lon"] = fmean(m["longitude"] for m in cl["members"])
        cl["n"] = len(cl["members"])
        cl["priority"] = max(SOURCE_PRIORITY[m["source"]] for m in cl["members"])
        cl["sources"] = sorted({m["source"] for m in cl["members"]})

    clusters.sort(key=lambda cl: (-cl["n"], -cl["priority"]))

    if clusters:
        best = clusters[0]
        if best["n"] >= 2:
            quality = "exact"
        elif "openskimap" in best["sources"]:
            quality = "openskimap"
        elif "wikidata" in best["sources"]:
            quality = "wikidata"
        else:
            # одиночный источник без подтверждения — координата не подтверждена
            quality = "review"

        if quality != "review":
            sources = list(best["sources"])
            # Кросс-чек с OSM-центроидом зоны катания (только метаданные, точку не меняем).
            if osm is not None and haversine_km(
                best["lat"], best["lon"], osm["latitude"], osm["longitude"]
            ) <= 2.0:
                sources = sorted(set(sources + ["osm_centroid"]))
            return {
                "chosen": {"latitude": round(best["lat"], 6), "longitude": round(best["lon"], 6)},
                "quality": quality,
                "cluster_size": best["n"],
                "sources_agreed": sources,
            }

    # Fallback: OSM-центроид зоны катания (когда вики-источники не дали точку курорта).
    if osm is not None:
        return {
            "chosen": {"latitude": round(osm["latitude"], 6), "longitude": round(osm["longitude"], 6)},
            "quality": "osm_centroid",
            "cluster_size": 1,
            "sources_agreed": ["osm_centroid"],
        }

    return {
        "chosen": None,
        "quality": "review",
        "reason": "нет подтверждённой координаты курорта",
    }


def region_in_rosstat(region: str) -> bool:
    """Есть ли регион в данных Росстата (поездки trips_2025)."""
    key = region_key(region)
    with open(RAW_DIR / "rosstat_tourist_trips.csv", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file, delimiter=";"):
            raw = row["Ряд"].rsplit(" — ", 1)[0].strip()
            if region_key(raw) == key:
                return True
    return False


def assess_resort(
    name: str, region: str, settlement: str = "",
    lat: float | None = None, lon: float | None = None,
) -> dict[str, Any]:
    """Оценить один курорт (без записи в seed): геокодинг + регион в Росстате."""
    resort = {
        "resort_id": "ASSESS", "name_ru": name, "region": region, "settlement": settlement,
        "latitude": lat, "longitude": lon,
    }
    candidates = gather_candidates(resort)
    decision = select_coordinate(resort, candidates)
    return {
        "name_ru": name,
        "region": region,
        "chosen": decision["chosen"],
        "quality": decision["quality"],
        "sources": decision.get("sources_agreed", []),
        "reason": decision.get("reason"),
        "region_in_rosstat": region_in_rosstat(region),
    }


def main() -> None:
    args = parse_args()
    resorts = load_resorts()

    if args.resort:
        wanted = {s.strip() for s in args.resort.split(",") if s.strip()}
        resorts = [r for r in resorts if r["resort_id"] in wanted]
    if args.limit:
        resorts = resorts[: args.limit]

    collected_at = datetime.now(UTC).isoformat()
    reference = load_reference_coords()
    previous = load_previous_coords(args.output)

    # Для Overpass-fallback: если в seed нет координат — берём ориентир заказчика.
    for resort in resorts:
        if resort.get("latitude") is None and resort.get("longitude") is None:
            ref = reference.get(resort["resort_id"])
            if ref:
                resort["latitude"] = ref["latitude"]
                resort["longitude"] = ref["longitude"]

    # Инкрементальность: курорты с подтверждённой координатой (exact/osm_centroid)
    # не перегеокодируем, а переносим прошлый результат как есть (если не --force).
    skip_qualities = KEEP_QUALITIES if not args.force else set()
    todo: list[dict[str, Any]] = []
    carried: list[dict[str, Any]] = []
    for resort in resorts:
        prev = previous.get(resort["resort_id"])
        if prev and prev.get("quality_new") in skip_qualities and prev.get("chosen"):
            carried.append(prev)
        else:
            todo.append(resort)

    print(
        f"Обрабатываю {len(todo)} курортов, {len(carried)} пропущено "
        f"(уже exact/osm_centroid) ...",
        flush=True,
    )

    results: list[dict[str, Any]] = []
    for index, resort in enumerate(todo, start=1):
        rid = resort["resort_id"]
        print(f"[{index}/{len(todo)}] {rid} {resort['name_ru']}", flush=True)
        candidates = gather_candidates(resort)
        decision = select_coordinate(resort, candidates)

        # Fallback: автоопределение не дало координату — пробуем OSM-центроид вокруг
        # ориентира заказчика; если он тоже пуст, остаёмся на самом ориентире.
        if decision["chosen"] is None and rid in reference:
            ref = reference[rid]
            try:
                osm = osm_ski_centroid(ref["latitude"], ref["longitude"])
                if osm:
                    decision = {
                        "chosen": {
                            "latitude": round(osm["latitude"], 6),
                            "longitude": round(osm["longitude"], 6),
                        },
                        "quality": "osm_centroid",
                        "sources_agreed": ["osm_centroid"],
                        "reason": "OSM-центроид вокруг ориентира заказчика",
                    }
            except Exception as exc:  # noqa: BLE001
                print(f"  [osm-ref] {rid}: {type(exc).__name__}", flush=True)
            if decision["chosen"] is None:
                decision = {
                    "chosen": {
                        "latitude": ref["latitude"],
                        "longitude": ref["longitude"],
                    },
                    "quality": "reference",
                    "sources_agreed": [],
                    "reason": "автоопределение и OSM-уточнение не удались — координата-ориентир заказчика",
                }

        results.append(
            {
                "resort_id": rid,
                "name_ru": resort["name_ru"],
                "region": resort["region"],
                "candidates": candidates,
                "quality_new": decision["quality"],
                "sources_agreed": decision.get("sources_agreed", []),
                "chosen": decision["chosen"],
                "reason": decision.get("reason"),
            }
        )

    results.extend(carried)
    results.sort(key=lambda r: r["resort_id"])

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "collected_at": collected_at,
        "note": (
            "Перекрёстная проверка координат: OpenSkiMap → Wikidata P625 → "
            "OSM-центроид объектов катания. raw не изменяется."
        ),
        "resorts": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== Сводка ===", flush=True)
    print(f"{'id':<6}{'качество':<22}   курорт", flush=True)
    for r in results:
        q = r["quality_new"]
        print(f"{r['resort_id']:<6}{q:<22}   {r['name_ru']}", flush=True)
    print(f"\nСохранено: {args.output.resolve()}", flush=True)


if __name__ == "__main__":
    main()

