#!/usr/bin/env python3
"""Витрина atlas_catalog: материализация SQL-вьюх atlas_ratings + v_atlas_ratings_with_scenarios.

Один CSV для Страницы 1. Логика:
  1. pivot resort_preset_components (960 -> 192 «широких» строк) + merge
     (presets, resort_features, resort_scores, ranking_stability, scoring_weights)
     -> in-memory wide-таблица (81 колонка);
  2. три сценарных блока: all_top (192), all_diversity (~120), members top+diversity (~420);
  3. единый data/mart/atlas_catalog.csv (~732 строки x 86 колонок).

Перед выгрузкой числовые колонки округляются (1/2/0/3 знака — ROUND_1/ROUND_2/ROUND_0/ROUND_3);
скоринг и нормализация при этом не меняются (уже посчитаны в resort_scores).
Порядок колонок повторяет SQL-вьюху.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

MART = PROJECT_ROOT / "data" / "mart"

from src.common.mart_io import read_csv, write_csv  # noqa: E402

COMPONENT_ORDER = ("regional", "infrastructure", "winter", "accessibility", "price")

# Сырые поля resort_features, переносимые в wide-таблицу как есть (порядок SQL).
RAW_FIELDS = [
    "resort_id", "name_ru", "region", "latitude", "longitude",
    "details_url", "official_website_url", "skimap_url",
    "piste_length_km", "piste_min_elevation_m", "piste_max_elevation_m", "lift_lines_6km",
    "piste_difficulty_novice", "piste_difficulty_easy", "piste_difficulty_intermediate",
    "piste_difficulty_advanced", "piste_difficulty_expert", "piste_difficulty_freeride",
    "piste_difficulty_unknown",
    "piste_type_snow_park", "piste_type_nordic",
    "lodging_objects_6km", "food_objects_6km", "attraction_objects_6km", "transport_objects_6km",
    "avg_snowfall_cm_per_season", "avg_snow_days_per_season", "avg_freezing_days_per_season",
    "max_daily_snowfall_cm", "winter_mean_temperature_c",
    "nearest_airport_distance_km", "nearest_airport_iata",
    "trips_2025", "trips_growth_2025", "avg_stay_nights_2025",
    "price_months_count", "completeness_pct", "quality_flags", "coordinate_validation_status",
]

# 13 весов показателей: w_колонка -> indicator в scoring_weights.csv.
WEIGHT_INDICATORS = [
    ("w_trips", "region_trips"), ("w_growth", "region_growth"), ("w_stay", "avg_stay"),
    ("w_pistes", "pistes"), ("w_lifts", "lifts"), ("w_lodging", "lodging"),
    ("w_amenities", "amenities"), ("w_snow_days", "snow_days"), ("w_freezing_days", "freezing_days"),
    ("w_snowfall", "snowfall"), ("w_airport", "airport"), ("w_transport", "transport"),
    ("w_price", "price"),
]

SCENARIO_META = {
    "all_top": {
        "scenario_id": "all_top",
        "scenario_label": "Все курорты (топ)",
        "strategy_name_ru": "Топ по индексу",
        "size_label": "Все",
        "n": None,
    },
    "all_diversity": {
        "scenario_id": "all_diversity",
        "scenario_label": "Все регионы (разнообразие)",
        "strategy_name_ru": "Региональное разнообразие",
        "size_label": "Все",
        "n": None,
    },
}


def _round1(value: object) -> float:
    return round(float(value), 1)


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _num(value: object) -> object:
    """Пустое -> None, иначе строка как есть (тип выведет load_supabase)."""
    if value is None or value == "":
        return None
    return value


# Финальное округление числовых колонок при упаковке витрины.
# Скоринг и нормализация уже сделаны в resort_scores; здесь только упаковка.
ROUND_1 = {
    "scenario_score", "base_score", "confidence_score", "local_score",
    "regional_score", "infrastructure_score", "winter_score",
    "accessibility_score", "price_score",
    "regional_contribution", "infrastructure_contribution", "winter_contribution",
    "accessibility_contribution", "price_contribution",
    "piste_length_km", "winter_mean_temperature_c", "max_daily_snowfall_cm",
    "nearest_airport_distance_km",
}

ROUND_0 = {
    "scenario_rank", "base_rank", "local_rank", "stability_median_rank",
    "n", "price_months_count",
    "trips_2025", "lift_lines_6km", "lodging_objects_6km", "food_objects_6km",
    "attraction_objects_6km", "transport_objects_6km",
    "piste_min_elevation_m", "piste_max_elevation_m",
    "avg_snow_days_per_season", "avg_freezing_days_per_season",
    "avg_snowfall_cm_per_season",
    "regional_weight", "infrastructure_weight", "winter_weight",
    "accessibility_weight", "price_weight",
    "w_trips", "w_growth", "w_stay", "w_pistes", "w_lifts", "w_lodging",
    "w_amenities", "w_snow_days", "w_freezing_days", "w_snowfall",
    "w_airport", "w_transport", "w_price",
    "piste_difficulty_novice", "piste_difficulty_easy",
    "piste_difficulty_intermediate", "piste_difficulty_advanced",
    "piste_difficulty_expert", "piste_difficulty_freeride",
    "piste_difficulty_unknown",
}

ROUND_3 = {"trips_growth_2025", "completeness_pct"}

ROUND_2 = {"avg_stay_nights_2025"}


def _round_num(value: object, ndigits: int) -> object:
    """Округлить число до ndigits знаков; None/'' и нечисловое не трогаем."""
    if value is None or value == "":
        return None
    try:
        v = round(float(value), ndigits)
        return int(v) if ndigits == 0 else v
    except (TypeError, ValueError):
        return value


def _apply_rounding(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Финальный шаг упаковки: округление числовых колонок."""
    for row in rows:
        for field in ROUND_1:
            if field in row:
                row[field] = _round_num(row[field], 1)
        for field in ROUND_0:
            if field in row:
                row[field] = _round_num(row[field], 0)
        for field in ROUND_3:
            if field in row:
                row[field] = _round_num(row[field], 3)
        for field in ROUND_2:
            if field in row:
                row[field] = _round_num(row[field], 2)
    return rows


def build_wide() -> list[dict[str, Any]]:
    """Pivot resort_preset_components + merge -> 192 строки (84 колонки)."""
    presets = {p["preset_id"]: p for p in read_csv(MART / "presets.csv")}
    features = {f["resort_id"]: f for f in read_csv(MART / "resort_features.csv")}
    scores = {s["resort_id"]: s for s in read_csv(MART / "resort_scores.csv")}
    stab = {(s["resort_id"], s["preset_id"]): s for s in read_csv(MART / "ranking_stability.csv")}
    weights = {
        w["indicator"]: float(w["indicator_weight"])
        for w in read_csv(MART / "scoring_weights.csv")
    }

    groups: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
    for r in read_csv(MART / "resort_preset_components.csv"):
        groups[(r["preset_id"], r["resort_id"])][r["component"]] = r

    rows: list[dict[str, Any]] = []
    for (preset_id, resort_id), comps in sorted(groups.items()):
        first = next(iter(comps.values()))
        p = presets[preset_id]
        f = features.get(resort_id, {})
        s = scores.get(resort_id, {})
        st = stab.get((resort_id, preset_id), {})

        row: dict[str, Any] = {
            "analysis_version": first["analysis_version"],
            "preset_id": preset_id,
            "preset_name_ru": p["name_ru"],
            "preset_description": p["description"],
        }
        for field in RAW_FIELDS:
            row[field] = f.get(field)
        row["scenario_score"] = _round1(first["scenario_score"])
        row["scenario_rank"] = int(first["scenario_rank"])
        row["base_score"] = _round1(first["base_score"])
        row["base_rank"] = int(first["base_rank"])
        row["rank_change"] = int(first["rank_change"])
        row["has_observed_price"] = _to_bool(first["has_observed_price"])
        for comp in COMPONENT_ORDER:
            c = comps[comp]
            row[f"{comp}_score"] = _round1(c["component_score"])
            row[f"{comp}_contribution"] = _round1(c["contribution"])
        for w in ("regional_weight", "infrastructure_weight", "winter_weight",
                  "accessibility_weight", "price_weight"):
            row[w] = float(p[w])
        for w_col, ind in WEIGHT_INDICATORS:
            row[w_col] = weights[ind]
        row["stability_median_rank"] = _num(st.get("median_rank"))
        row["local_score"] = _num(st.get("local_score"))
        row["local_rank"] = _num(st.get("local_rank"))
        row["confidence_score"] = (
            _round1(s["confidence_score"]) if s.get("confidence_score") not in (None, "") else None
        )
        rows.append(row)
    return rows


def _with_meta(row: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out.update(meta)
    return out


def build_scenarios(wide: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Три сценарных блока: all_top + all_diversity + members (top+diversity)."""
    wide_by_key = {(r["preset_id"], r["resort_id"]): r for r in wide}

    rows = [_with_meta(r, SCENARIO_META["all_top"]) for r in wide]

    best: dict[tuple[str, str], dict[str, Any]] = {}
    for r in wide:
        key = (r["preset_id"], r["region"])
        cur = best.get(key)
        if cur is None or r["scenario_score"] > cur["scenario_score"]:
            best[key] = r
    rows += [
        _with_meta(r, SCENARIO_META["all_diversity"]) for _, r in sorted(best.items())
    ]

    scenarios = {s["scenario_id"]: s for s in read_csv(MART / "catalog_scenarios.csv")}
    member_rows = []
    for m in read_csv(MART / "catalog_members.csv"):
        s = scenarios[m["scenario_id"]]
        if s["strategy"] not in ("top", "diversity"):
            continue
        wide_row = wide_by_key.get((m["preset_id"], m["resort_id"]))
        if wide_row is None:
            continue
        out = dict(wide_row)
        out["scenario_id"] = m["scenario_id"]
        out["scenario_label"] = s["scenario_label"]
        out["strategy_name_ru"] = s["strategy_name_ru"]
        out["size_label"] = str(s["n"])
        out["n"] = int(s["n"])
        member_rows.append(out)
    member_rows.sort(key=lambda r: (r["scenario_id"], r["resort_id"]))

    return rows + member_rows


def validate(wide: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    assert len(wide) == 192, f"wide ожидалось 192, получено {len(wide)}"
    n_all_top = sum(1 for r in rows if r["scenario_id"] == "all_top")
    n_all_div = sum(1 for r in rows if r["scenario_id"] == "all_diversity")
    assert n_all_top == 192, n_all_top

    regions = {r["region"] for r in wide}
    assert n_all_div == 6 * len(regions), f"all_diversity: {n_all_div} != 6*{len(regions)}"

    member_rows = [r for r in rows if r["scenario_id"] not in ("all_top", "all_diversity")]
    scenarios = read_csv(MART / "catalog_scenarios.csv")
    expected = sum(
        int(s["n"]) for s in scenarios if s["strategy"] in ("top", "diversity")
    )
    assert len(member_rows) == expected, f"members: {len(member_rows)} != {expected}"


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    wide = build_wide()
    rows = build_scenarios(wide)
    rows = _apply_rounding(rows)
    validate(wide, rows)

    out = MART / "atlas_catalog.csv"
    write_csv(out, rows)
    print(f"atlas_catalog: {len(rows)} строк x {len(rows[0])} колонок")
    print(f"  all_top: {sum(1 for r in rows if r['scenario_id'] == 'all_top')}")
    print(f"  all_diversity: {sum(1 for r in rows if r['scenario_id'] == 'all_diversity')}")
    print(f"  members: {sum(1 for r in rows if r['scenario_id'] not in ('all_top', 'all_diversity'))}")
    print(f"Сохранено: {out}")


if __name__ == "__main__":
    main()
