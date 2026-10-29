#!/usr/bin/env python3
"""Рейтинг resort_scores: нормировка 13 показателей и popularity_score.

Методика (из ТЗ / эталона prepare_model_data.py):
  * Min-max        100·(x−min)/(max−min)              — снежные/морозные дни;
  * Log min-max    100·(ln(1+x)−ln(1+min))/...         — поездки, OSM, снегопад;
  * Обратная       100 − log_min_max                   — аэропорт, цена;
  * Рост           clip(50 + 200·growth, 0, 100)       — рост поездок;
  * Длительность   clip((nights−1)/6·100, 0, 100)      — ночёвок на поездку.

Веса (сумма = 100): региональный спрос 40, инфраструктура 25, зимние условия 20,
доступность 10, цена 5.

confidence_score = 50·completeness_pct + 25·has_price + 25·has_verified_coords.

Расшифровка слагаемых confidence_score (см. контрольные пункты аудита):
  * completeness_pct — доля заполненных обязательных полей в интервале 0..1
    (НЕ проценты 0..100; поле названо «_pct» по инерции эталона, хранит дробь);
  * has_price — наличие наблюдаемой цены ски-пасса (adult_skipass_avg_rub не None);
  * has_verified_coords — coordinate_validation_status == "confirmed"
    (только «confirmed»; «provisional»/«warn» и «needs_review» не подтверждены).

Отличие от эталона: «точные координаты» определяются по coordinate_validation_status
(confirmed/provisional/needs_review), который выводится из coordinate_status в
build_resort_features.py. «warn» (сдвиг 8–15 км) теперь = «provisional», а не
подтверждённая координата (ТЗ дашборда §3.2).

Вход: data/mart/resort_features.csv. Выход: data/mart/resort_scores.csv.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
MART = PROJECT_ROOT / "data" / "mart"
REFERENCE = PROJECT_ROOT / "data" / "reference"

from src.common.mart_io import read_csv, write_csv  # noqa: E402

def _load_weights_config() -> dict[str, Any]:
    """Прочитать и проверить веса из data/reference/scoring_weights.json."""
    path = REFERENCE / "scoring_weights.json"
    config = json.loads(path.read_text(encoding="utf-8"))

    indicators = config["indicator_weights"]
    components = config["components"]
    component_weights = config["component_weights"]

    assert abs(sum(float(v) for v in indicators.values()) - 100.0) <= 0.01, (
        "сумма 13 весов показателей != 100"
    )
    assert abs(sum(float(v) for v in component_weights.values()) - 100.0) <= 0.01, (
        "сумма 5 весов компонентов != 100"
    )
    flat = [ind for inds in components.values() for ind in inds]
    assert sorted(flat) == sorted(indicators), "набор индикаторов в components != indicator_weights"
    for comp, inds in components.items():
        total = sum(float(indicators[ind]) for ind in inds)
        assert abs(total - float(component_weights[comp])) <= 0.01, (
            f"{comp}: сумма под-весов != весу компонента"
        )
    return config


_WEIGHTS_CONFIG = _load_weights_config()

# 13 весов показателей (сумма = 100) — из конфига.
WEIGHTS: dict[str, float] = {
    k: float(v) for k, v in _WEIGHTS_CONFIG["indicator_weights"].items()
}

# Компонентные баллы (0–100): взвешенная средняя под-баллов внутри компонента.
# «price» состоит из одного показателя, поэтому price_score — одновременно 13-й балл
# и компонент «Цена» (отдельное поле не дублируем).
COMPONENTS: dict[str, list[tuple[str, float]]] = {
    comp: [(ind + "_score", float(_WEIGHTS_CONFIG["indicator_weights"][ind])) for ind in inds]
    for comp, inds in _WEIGHTS_CONFIG["components"].items()
}

# Новые компонентные поля, попадающие в resort_scores (price_score уже среди 13 баллов).
COMPONENT_SCORE_FIELDS = ("regional_score", "infrastructure_score", "winter_score", "accessibility_score")


def component_score(scores: dict[str, float], subscores: list[tuple[str, float]]) -> float:
    """Взвешенная средняя под-баллов → компонентный балл 0–100."""
    total = sum(scores[key] * weight for key, weight in subscores)
    return total / sum(weight for _, weight in subscores)


def minmax(values: list[float], value: float, *, log: bool = False, inverse: bool = False) -> float:
    """0–100 min-max балл (опц. log1p-трансформация и инверсия)."""
    transformed = [math.log1p(item) if log else item for item in values]
    current = math.log1p(value) if log else value
    low, high = min(transformed), max(transformed)
    score = 50.0 if high == low else 100.0 * (current - low) / (high - low)
    score = 100.0 - score if inverse else score
    return max(0.0, min(100.0, score))


def climate_score(values: list[float], raw: float | None, *, log: bool = False) -> float:
    """Климатический балл: отсутствие данных (None) → нейтральные 50, иначе min-max.

    Отличие от `or 0`: None (нет данных) не превращается в 0 баллов, а даёт
    нейтральный балл, и не искажает min/max распределения искусственным нулём.
    """
    if raw is None:
        return 50.0
    return minmax(values, float(raw), log=log)


def clipped_growth_score(value: float | None) -> float:
    """−25% → 0, +25% → 100, с обрезкой."""
    if value is None:
        return 50.0
    return max(0.0, min(100.0, 50.0 + 200.0 * value))


def clipped_stay_score(value: float | None) -> float:
    """1–7 ночей на поездку → 0–100."""
    if value is None:
        return 50.0
    return max(0.0, min(100.0, (value - 1.0) / 6.0 * 100.0))


def load_features() -> list[dict[str, Any]]:
    return read_csv(MART / "resort_features.csv")


def build_scores() -> list[dict[str, Any]]:
    features = load_features()

    trips_levels = [float(f["trips_2025"]) for f in features]
    pistes = [float(f["piste_segments_6km"] or 0) for f in features]
    lifts = [float(f["lift_lines_6km"] or 0) for f in features]
    lodging = [float(f["lodging_objects_6km"] or 0) for f in features]
    amenities = [
        float((f["food_objects_6km"] or 0) + (f["attraction_objects_6km"] or 0)) for f in features
    ]
    snow_days = [float(f["avg_snow_days_per_season"]) for f in features if f["avg_snow_days_per_season"] is not None]
    freezing_days = [float(f["avg_freezing_days_per_season"]) for f in features if f["avg_freezing_days_per_season"] is not None]
    snowfall = [float(f["avg_snowfall_cm_per_season"]) for f in features if f["avg_snowfall_cm_per_season"] is not None]
    airport_distance = [float(f["nearest_airport_distance_km"] or 0) for f in features]
    transport = [float(f["transport_objects_6km"] or 0) for f in features]
    observed_prices = [float(f["adult_skipass_avg_rub"]) for f in features if f["adult_skipass_avg_rub"]]

    rows: list[dict[str, Any]] = []
    for f in features:
        price = f["adult_skipass_avg_rub"]
        scores = {
            "region_trips_score": minmax(trips_levels, float(f["trips_2025"]), log=True),
            "region_growth_score": clipped_growth_score(f["trips_growth_2025"]),
            "avg_stay_score": clipped_stay_score(f["avg_stay_nights_2025"]),
            "pistes_score": minmax(pistes, float(f["piste_segments_6km"] or 0), log=True),
            "lifts_score": minmax(lifts, float(f["lift_lines_6km"] or 0), log=True),
            "lodging_score": minmax(lodging, float(f["lodging_objects_6km"] or 0), log=True),
            "amenities_score": minmax(
                amenities,
                float((f["food_objects_6km"] or 0) + (f["attraction_objects_6km"] or 0)),
                log=True,
            ),
            "snow_days_score": climate_score(snow_days, f["avg_snow_days_per_season"]),
            "freezing_days_score": climate_score(freezing_days, f["avg_freezing_days_per_season"]),
            "snowfall_score": climate_score(snowfall, f["avg_snowfall_cm_per_season"], log=True),
            "airport_score": minmax(
                airport_distance, float(f["nearest_airport_distance_km"] or 0), log=True, inverse=True
            ),
            "transport_score": minmax(transport, float(f["transport_objects_6km"] or 0), log=True),
            "price_score": (
                minmax(observed_prices, float(price), log=True, inverse=True) if price else 50.0
            ),
        }
        total = sum(scores[key + "_score"] * weight for key, weight in WEIGHTS.items()) / 100.0
        confidence = (
            50.0 * float(f.get("completeness_pct") or 0)
            + 25.0 * (1.0 if price else 0.0)
            + 25.0 * (1.0 if f.get("coordinate_validation_status") == "confirmed" else 0.0)
        )
        rows.append(
            {
                "resort_id": f["resort_id"],
                "name_ru": f["name_ru"],
                "region": f["region"],
                "latitude": f["latitude"],
                "longitude": f["longitude"],
                **scores,
                "regional_score": component_score(scores, COMPONENTS["regional"]),
                "infrastructure_score": component_score(scores, COMPONENTS["infrastructure"]),
                "winter_score": component_score(scores, COMPONENTS["winter"]),
                "accessibility_score": component_score(scores, COMPONENTS["accessibility"]),
                "popularity_score": total,
                "confidence_score": confidence,
                "details_url": f.get("details_url"),
                "details_url_source": f.get("details_url_source"),
            }
        )

    rows.sort(key=lambda r: r["popularity_score"], reverse=True)
    for rank, r in enumerate(rows, start=1):
        r["rank"] = rank
    return rows


def validate(rows: list[dict[str, Any]]) -> None:
    assert abs(sum(WEIGHTS.values()) - 100.0) <= 0.001, "сумма весов != 100"
    n = len(load_features())
    assert len(rows) == n, f"ожидалось {n} строк, получено {len(rows)}"
    assert len({r["resort_id"] for r in rows}) == n, "resort_id не уникальны"

    score_fields = [k + "_score" for k in WEIGHTS]
    all_score_fields = score_fields + list(COMPONENT_SCORE_FIELDS)
    for r in rows:
        for field in all_score_fields:
            v = r[field]
            assert 0.0 <= v <= 100.0, f"{r['resort_id']}.{field} = {v} вне 0..100"
        assert 0.0 <= r["popularity_score"] <= 100.0, "popularity_score вне 0..100"
        assert 0.0 <= r["confidence_score"] <= 100.0, "confidence_score вне 0..100"
        for field in all_score_fields + ["popularity_score", "confidence_score"]:
            assert math.isfinite(r[field]), f"{r['resort_id']}.{field} не конечен"


def build_weights_table() -> list[dict[str, Any]]:
    """13 весов показателей с группировкой по компонентам (витрина для дашборда)."""
    cfg = _WEIGHTS_CONFIG
    version = cfg.get("analysis_version") or "v1"
    component_names = cfg.get("component_names_ru") or {}
    indicator_names = cfg.get("indicator_names_ru") or {}
    component_weights = cfg["component_weights"]
    indicator_weights = cfg["indicator_weights"]
    components = cfg["components"]

    rows: list[dict[str, Any]] = []
    for comp, inds in components.items():
        for ind in inds:
            rows.append({
                "analysis_version": version,
                "component": comp,
                "component_name_ru": component_names.get(comp, comp),
                "component_weight": float(component_weights[comp]),
                "indicator": ind,
                "indicator_name_ru": indicator_names.get(ind, ind),
                "indicator_weight": float(indicator_weights[ind]),
            })
    return rows


def main() -> None:
    rows = build_scores()
    validate(rows)

    out = MART / "resort_scores.csv"
    write_csv(out, rows)

    weights = build_weights_table()
    weights_out = MART / "scoring_weights.csv"
    write_csv(weights_out, weights)

    print("Топ-12:")
    for r in rows[:12]:
        print(f"  {r['rank']:>2}. {r['name_ru']:<22} {r['popularity_score']:.1f}  (conf {r['confidence_score']:.0f})")
    print(f"Сохранено: {out}")
    print(f"Сохранено: {weights_out} ({len(weights)} строк весов)")


if __name__ == "__main__":
    main()
