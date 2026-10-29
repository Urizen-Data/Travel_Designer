#!/usr/bin/env python3
"""Клиент OpenSkiMap API (https://api.openskimap.org) — прямой поиск skiArea.

Простой надёжный клиент: search_resort() делает GET /search?query={name} и
возвращает объекты type == "skiArea". Никаких fuzzy/spatial/транслитерации —
всё, что не находится прямым поиском, уходит в fallback (Wikidata/Overpass/справочник).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "TravelDesignerStudentWorkshop/1.0 open-data-research"

# Сложность трасс OpenSkiMap (конвенция Europe) -> наши поля piste_difficulty_*.
DIFFICULTY_MAP = {
    "novice": "piste_difficulty_novice",
    "easy": "piste_difficulty_easy",
    "intermediate": "piste_difficulty_intermediate",
    "advanced": "piste_difficulty_advanced",
    "expert": "piste_difficulty_expert",
    "freeride": "piste_difficulty_freeride",
    "extreme": "piste_difficulty_extreme",
}

# Очевидные синонимы названий (наш справочник -> имя в OpenSkiMap).
NAME_ALIASES = {
    "Газпром Поляна": "Газпром",
}


class OpenSkiMapError(Exception):
    """Сетевая/серверная ошибка OpenSkiMap (не 404)."""


class OpenSkiMapClient:
    def __init__(
        self,
        base_url: str = "https://api.openskimap.org",
        timeout: int = 60,
        throttle: float = 1.0,
        max_attempts: int = 3,
        retry_delays: tuple[float, ...] = (1.0, 3.0, 5.0),
        user_agent: str = USER_AGENT,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.throttle = throttle  # пауза между запросами (rate limit публичного API)
        self.max_attempts = max_attempts
        self.retry_delays = retry_delays  # задержки между повторами
        self.user_agent = user_agent

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = self.base_url + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            if attempt == 0:
                time.sleep(self.throttle)
            else:
                idx = attempt - 1
                delay = self.retry_delays[idx] if idx < len(self.retry_delays) else self.retry_delays[-1]
                time.sleep(delay)
            req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return None
                last_error = exc
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.max_attempts - 1:
                    continue  # rate limit / серверная ошибка — повторяем
                raise OpenSkiMapError(f"HTTP {exc.code} на {url}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < self.max_attempts - 1:
                    continue  # сеть/таймаут — повторяем
                raise OpenSkiMapError(f"{type(exc).__name__} на {url}") from exc
        raise OpenSkiMapError(
            f"запрос не удался после {self.max_attempts} попыток ({type(last_error).__name__})"
        )

    def search_resort(self, name: str) -> list[dict[str, Any]]:
        """Прямой поиск: GET /search?query={name} -> список Feature type == 'skiArea'."""
        queries = [name]
        alias = NAME_ALIASES.get(name)
        if alias:
            queries.append(alias)
        for query in queries:
            payload = self._get("/search", {"query": query})
            if not isinstance(payload, list):
                continue
            areas = [
                f for f in payload
                if isinstance(f, dict) and f.get("properties", {}).get("type") == "skiArea"
            ]
            if areas:
                return areas
        return []

    def get_resort_details(self, ski_area_id: str) -> Any:
        """Полная статистика по ID (best-effort; в API нет GET /areas/{id})."""
        return self._get(f"/areas/{ski_area_id}")

    @staticmethod
    def extract_coordinate(geometry: dict[str, Any]) -> tuple[float, float] | None:
        """Координата: Point — напрямую, Polygon/MultiPolygon — центроид внешних колец."""
        t = geometry.get("type")
        if t == "Point":
            c = geometry["coordinates"]
            return c[0], c[1]
        if t == "Polygon":
            rings = [geometry["coordinates"][0]]
        elif t == "MultiPolygon":
            rings = [poly[0] for poly in geometry["coordinates"]]
        else:
            return None
        pts = [p for ring in rings for p in ring]
        if not pts:
            return None
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)

    @staticmethod
    def map_statistics(feature: dict[str, Any]) -> dict[str, Any]:
        """Преобразовать statistics skiArea -> поля курорта (piste/lift/высоты).

        Если у зоны нет разбивки по сложности — соответствующие поля остаются None
        (не 0), чтобы не выдумывать данные.
        """
        stats = (feature.get("properties", {}) or {}).get("statistics") or {}
        runs = stats.get("runs") or {}
        lifts = stats.get("lifts") or {}

        downhill = (runs.get("byActivity") or {}).get("downhill") or {}
        by_diff = downhill.get("byDifficulty") or {}

        out: dict[str, Any] = {
            "piste_difficulty_novice": None,
            "piste_difficulty_easy": None,
            "piste_difficulty_intermediate": None,
            "piste_difficulty_advanced": None,
            "piste_difficulty_expert": None,
            "piste_difficulty_freeride": None,
            "piste_difficulty_extreme": None,
            "piste_difficulty_unknown": None,
            "piste_length_km": None,
            "piste_min_elevation_m": None,
            "piste_max_elevation_m": None,
            "lift_lines_6km": None,
            "lift_min_elevation_m": None,
            "lift_max_elevation_m": None,
        }

        total_runs = 0
        total_length_km = 0.0
        for diff_key, item in by_diff.items():
            if not isinstance(item, dict):
                continue
            count = item.get("count")
            if count is not None:
                total_runs += int(count)
                total_length_km += float(item.get("lengthInKm") or 0.0)
            field = DIFFICULTY_MAP.get(diff_key)
            if field and count is not None:
                out[field] = int(count)
            elif count is not None:
                # нестандартная сложность (например "other") -> unknown
                out["piste_difficulty_unknown"] = int(count)

        out["piste_segments_6km"] = total_runs or None
        out["piste_ways_total"] = total_runs or None
        out["piste_length_km"] = round(total_length_km, 2) if total_runs else None
        out["piste_min_elevation_m"] = runs.get("minElevation")
        out["piste_max_elevation_m"] = runs.get("maxElevation")

        by_type = lifts.get("byType") or {}
        total_lifts = sum(
            int(t.get("count") or 0) for t in by_type.values() if isinstance(t, dict)
        )
        out["lift_lines_6km"] = total_lifts or None
        out["lift_min_elevation_m"] = lifts.get("minElevation")
        out["lift_max_elevation_m"] = lifts.get("maxElevation")

        known = sum(out.get(f) or 0 for f in DIFFICULTY_MAP.values())
        out["piste_difficulty_coverage"] = round(known / total_runs, 4) if total_runs else None

        return out

