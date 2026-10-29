#!/usr/bin/env python3
"""Сбор внешних ссылок на курорты (details_url) и Skimap ID.

Каскад выбора details_url (Fallback Chain):
  1. Skimap  — skimap.org/skiareas/view/{id} (OpenSkiMap sources / Wikidata P6400 / known);
  2. Wikipedia — ru.wikipedia.org/wiki/{title} (sitelink из Wikidata);
  3. Wikidata — wikidata.org/wiki/{QID};
  4. NULL.

Записывает skimap_id, skimap_url, details_url, details_url_source в resorts.json.

Запуск:
  python src/collect/fetch_skimap_ids.py
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.collect.openskimap_client import OpenSkiMapClient, OpenSkiMapError  # noqa: E402
from src.collect.geocode_resorts import (  # noqa: E402
    THROTTLE,
    WIKIDATA_ENTITY,
    request_json,
    wikidata_search,
)

PREPARED_DIR = PROJECT_ROOT / "data" / "prepared"

# Проверенные вручную ID (Skimap.org не отдаёт публичный JSON-поиск).
KNOWN_SKIMAP_IDS = {
    "КолаСпортЛэнд": 3081,
}

SKIMAP_SOURCE_RE = re.compile(r"skimap\.org:(\d+)")


def skimap_id_from_sources(sources: str | None) -> str | None:
    """Извлечь Skimap ID из строки openskimap_sources (паттерн 'skimap.org:2678')."""
    if not sources:
        return None
    match = SKIMAP_SOURCE_RE.search(sources)
    return match.group(1) if match else None


def resolve_skimap(name: str, openskimap_sources: str | None) -> tuple[int | None, str]:
    """skimap_id и skimap_url: openskimap_sources → известные ID → базовый URL."""
    sid = skimap_id_from_sources(openskimap_sources)
    if sid:
        return int(sid), f"https://skimap.org/skiareas/view/{sid}"
    if name in KNOWN_SKIMAP_IDS:
        sid = KNOWN_SKIMAP_IDS[name]
        return sid, f"https://skimap.org/skiareas/view/{sid}"
    return None, "https://skimap.org"


def openskimap_skimap_id(name: str) -> str | None:
    """Skimap ID из поля sources OpenSkiMap (type == 'skimap.org')."""
    try:
        areas = OpenSkiMapClient().search_resort(name)
    except OpenSkiMapError:
        return None
    if not areas:
        return None
    for s in (areas[0].get("properties", {}) or {}).get("sources") or []:
        if s.get("type") == "skimap.org" and s.get("id") is not None:
            return str(s["id"])
    return None


def wikidata_entity(qid: str) -> dict:
    """Полный объект Wikidata (claims + sitelinks + labels)."""
    payload = request_json(f"{WIKIDATA_ENTITY}/{qid}.json", throttle=THROTTLE["wikidata"])
    return payload.get("entities", {}).get(qid, {})


def resolve(name: str, settlement: str) -> dict:
    """Вернуть dict: skimap_id, skimap_url, details_url, details_url_source, wikidata_qid."""
    out = {
        "skimap_id": None,
        "skimap_url": None,
        "details_url": None,
        "details_url_source": None,
        "wikidata_qid": None,
    }

    def set_skimap(sid: str) -> None:
        out["skimap_id"] = int(sid)
        out["skimap_url"] = f"https://skimap.org/skiareas/view/{sid}"
        out["details_url"] = out["skimap_url"]
        out["details_url_source"] = "Skimap"

    # Приоритет 1: Skimap (OpenSkiMap sources).
    sid = openskimap_skimap_id(name)
    if sid:
        set_skimap(sid)
        return out

    # Приоритет 1: Skimap (известные ID).
    if name in KNOWN_SKIMAP_IDS:
        set_skimap(KNOWN_SKIMAP_IDS[name])
        return out

    # Wikidata: QID -> P6400 / sitelinks / сам объект.
    try:
        qid = wikidata_search(name, settlement)
    except Exception:
        qid = None
    if not qid:
        return out
    out["wikidata_qid"] = qid

    try:
        entity = wikidata_entity(qid)
    except Exception:
        entity = {}

    # Приоритет 1: Skimap (P6400).
    claim = entity.get("claims", {}).get("P6400")
    if claim:
        try:
            set_skimap(claim[0]["mainsnak"]["datavalue"]["value"])
            return out
        except (KeyError, TypeError, ValueError):
            pass

    # Приоритет 2: Wikipedia (русская статья через sitelinks).
    ruwiki = entity.get("sitelinks", {}).get("ruwiki")
    if ruwiki and ruwiki.get("title"):
        title = urllib.parse.quote(ruwiki["title"])
        out["details_url"] = f"https://ru.wikipedia.org/wiki/{title}"
        out["details_url_source"] = "Wikipedia"
        return out

    # Приоритет 3: Wikidata.
    out["details_url"] = f"https://www.wikidata.org/wiki/{qid}"
    out["details_url_source"] = "Wikidata"
    return out


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    path = PREPARED_DIR / "resorts.json"
    resorts = json.loads(path.read_text(encoding="utf-8"))

    for r in resorts:
        # skimap_url заполняем локально из openskimap_sources (без сети).
        skimap_id, skimap_url = resolve_skimap(r["name_ru"], r.get("openskimap_sources"))
        r["skimap_id"] = skimap_id
        r["skimap_url"] = skimap_url

        # details_url — каскад Skimap → Wikipedia → Wikidata (как раньше).
        d = resolve(r["name_ru"], r.get("settlement", ""))
        r["details_url"] = (d["details_url"] or "").strip() or None
        r["details_url_source"] = d["details_url_source"]
        r["wikidata_qid"] = d["wikidata_qid"]

    path.write_text(json.dumps(resorts, ensure_ascii=False, indent=2), encoding="utf-8")

    print("| Курорт | Источник ссылки | URL |")
    print("|---|---|---|")
    for r in resorts:
        src = r.get("details_url_source") or "—"
        url = r.get("details_url") or "—"
        print(f"| {r['name_ru']} | {src} | {url} |")


if __name__ == "__main__":
    main()
