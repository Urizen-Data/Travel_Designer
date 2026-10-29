#!/usr/bin/env python3
"""Сценарии стартового каталога и сравнение с топ-N.

Считает поверх data/mart/resort_preset_components.csv (scenario_score по 6 пресетам)
и resort_features.csv (названия, регионы, статус координат). Подбор — управленческий сценарий,
а не «единственно правильная» подборка: показываем компромисс между средним
индексом и разнообразием.

Стратегии (для N = 5, 8, 10, 12):
  * top                 — топ-N по индексу потенциала (без региональных ограничений);
  * diversity           — не более одного курорта на регион (максимум разнообразия),
                          отбор: лучший курорт каждого региона, затем топ-N по индексу;
  * diversity_verified  — то же, но при прочих равных предпочитаются курорты с
                          подтверждёнными координатами (coordinate_validation_status
                          == "confirmed").

Целевая функция — сумма базовых индексов, без оптимизации прибыли. Для каждого
сценария считаются KPI сравнения с топ-N той же версии. «Замены» (добавленные /
исключённые курорты) вычисляются на стороне BI из catalog_members vs топ-N.

Ограничения обрабатываются честно: невыполнимые сочетания получают status
"infeasible" и не выдаются как успешная подборка.

Выход:
  * data/mart/catalog_scenarios.csv — сценарий × параметры и KPI;
  * data/mart/catalog_members.csv   — сценарий × выбранный курорт.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

MART = PROJECT_ROOT / "data" / "mart"
ANALYTICS = MART

from src.common.mart_io import read_csv, write_csv  # noqa: E402

N_VALUES = [5, 8, 10, 12]

STRATEGIES = {
    "top": "Топ по индексу",
    "diversity": "Региональное разнообразие",
    "diversity_verified": "Разнообразие + подтверждённые координаты",
}

CONFIRMED_STATUS = "confirmed"

# Для отбора берём одну строку на (preset, resort): scenario_score дублируется по 5 компонентам.
PRESET_COMPONENT_KEY = "regional"


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def load_presets() -> list[dict[str, Any]]:
    """presets.csv (preset_id + name_ru) — порядок пресетов для сортировки сценариев."""
    return read_csv(MART / "presets.csv")


def load_scores_for_preset(preset_id: str) -> list[dict[str, Any]]:
    """scenario_score/rank текущего пресета + поля из resort_features (по resort_id)."""
    components = read_csv(MART / "resort_preset_components.csv")
    features = read_csv(MART / "resort_features.csv")
    by_id = {f["resort_id"]: f for f in features}

    scores: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in components:
        if r["preset_id"] != preset_id or r["component"] != PRESET_COMPONENT_KEY:
            continue
        if r["resort_id"] in seen:
            continue
        seen.add(r["resort_id"])
        f = by_id.get(r["resort_id"], {})
        scores.append({
            "resort_id": r["resort_id"],
            "name_ru": f.get("name_ru"),
            "region": f.get("region"),
            "scenario_score": float(r["scenario_score"]),
            "scenario_rank": int(r["scenario_rank"]),
            "has_observed_price": _to_bool(r.get("has_observed_price")),
            "coordinate_validation_status": f.get("coordinate_validation_status"),
        })
    return scores


def is_confirmed(r: dict[str, Any]) -> bool:
    return r.get("coordinate_validation_status") == CONFIRMED_STATUS


def has_price(r: dict[str, Any]) -> bool:
    return bool(r.get("has_observed_price"))


def _by_index(r: dict[str, Any]) -> tuple:
    return (-r["scenario_score"], r["resort_id"])


def _by_verified_then_index(r: dict[str, Any]) -> tuple:
    return (0 if is_confirmed(r) else 1, -r["scenario_score"], r["resort_id"])


def select_top(scores: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    return sorted(scores, key=_by_index)[:n]


def best_per_region(scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for r in scores:
        cur = best.get(r["region"])
        if cur is None or r["scenario_score"] > cur["scenario_score"]:
            best[r["region"]] = r
    return list(best.values())


def select_diversity(scores: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    return sorted(best_per_region(scores), key=_by_index)[:n]


def select_diversity_verified(scores: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    return sorted(best_per_region(scores), key=_by_verified_then_index)[:n]


def compute_metrics(selected: list[dict[str, Any]], reference: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(selected)
    region_counts = Counter(r["region"] for r in selected)
    avg_index = mean(r["scenario_score"] for r in selected)
    ref_avg = mean(r["scenario_score"] for r in reference)
    return {
        "resort_count": n,
        "region_count": len(region_counts),
        "max_region_share": round(max(region_counts.values()) / n, 4),
        "avg_index": round(avg_index, 2),
        "avg_index_vs_top": round(avg_index - ref_avg, 2),
        "confirmed_coords_count": sum(1 for r in selected if is_confirmed(r)),
        "observed_price_count": sum(1 for r in selected if has_price(r)),
    }


def build_scenarios(
    preset_ids: list[str], preset_names: dict[str, str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    scenario_rows: list[dict[str, Any]] = []
    member_rows: list[dict[str, Any]] = []
    selectors = {
        "top": select_top,
        "diversity": select_diversity,
        "diversity_verified": select_diversity_verified,
    }
    for preset_id in preset_ids:
        scores = load_scores_for_preset(preset_id)
        preset_name = preset_names[preset_id]
        for n in N_VALUES:
            reference = select_top(scores, n)
            for name, selector in selectors.items():
                selected = selector(scores, n)
                feasible = len(selected) == n
                scenario_id = f"{preset_id}_{name}_n{n}"
                metrics = compute_metrics(selected, reference)
                scenario_rows.append(
                    {
                        "scenario_id": scenario_id,
                        "preset_id": preset_id,
                        "preset_name_ru": preset_name,
                        "strategy": name,
                        "strategy_name_ru": STRATEGIES[name],
                        "scenario_label": f"{STRATEGIES[name]} · {preset_name} · N={n}",
                        "n": n,
                        "max_per_region": None if name == "top" else 1,
                        "status": "feasible" if feasible else "infeasible",
                        **metrics,
                    }
                )
                for i, r in enumerate(selected, 1):
                    member_rows.append(
                        {
                            "scenario_id": scenario_id,
                            "preset_id": preset_id,
                            "resort_id": r["resort_id"],
                            "name_ru": r["name_ru"],
                            "region": r["region"],
                            "scenario_score": r["scenario_score"],
                            "scenario_rank": r["scenario_rank"],
                            "rank_within_scenario": i,
                            "coordinate_validation_status": r["coordinate_validation_status"],
                            "has_observed_price": r["has_observed_price"],
                        }
                    )
    return scenario_rows, member_rows


def validate(
    scenario_rows: list[dict[str, Any]],
    member_rows: list[dict[str, Any]],
    preset_ids: list[str],
) -> None:
    assert len(scenario_rows) == len(preset_ids) * len(N_VALUES) * len(STRATEGIES)
    for pid in preset_ids:
        p = [s for s in scenario_rows if s["preset_id"] == pid]
        assert len(p) == len(N_VALUES) * len(STRATEGIES), pid

    for row in scenario_rows:
        assert row["resort_count"] == row["n"], row["scenario_id"]
        members = [m for m in member_rows if m["scenario_id"] == row["scenario_id"]]
        assert len(members) == row["n"], row["scenario_id"]
        assert len({m["resort_id"] for m in members}) == row["n"], row["scenario_id"]
        assert 0.0 <= row["max_region_share"] <= 1.0

        avg = mean(m["scenario_score"] for m in members)
        assert abs(avg - row["avg_index"]) <= 0.02, row["scenario_id"]

        if row["strategy"] == "top":
            assert abs(row["avg_index_vs_top"]) <= 0.02, row["scenario_id"]
        if row["strategy"].startswith("diversity"):
            assert row["avg_index_vs_top"] <= 0.02, row["scenario_id"]
            assert row["region_count"] == row["n"], row["scenario_id"]


def _configure_stdout() -> None:
    """UTF-8 для вывода, иначе символы вроде Δ/× падают в консоли cp1251."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main() -> None:
    _configure_stdout()
    presets = load_presets()
    preset_ids = [p["preset_id"] for p in presets]
    preset_names = {p["preset_id"]: p["name_ru"] for p in presets}

    scenario_rows, member_rows = build_scenarios(preset_ids, preset_names)
    validate(scenario_rows, member_rows, preset_ids)

    ANALYTICS.mkdir(parents=True, exist_ok=True)

    scenarios_out = ANALYTICS / "catalog_scenarios.csv"
    write_csv(scenarios_out, scenario_rows)

    members_out = ANALYTICS / "catalog_members.csv"
    write_csv(members_out, member_rows)

    print("Сценарии каталога (6 пресетов × 3 стратегии × 4 N):")
    header = (
        f"{'сценарий':<28}{'N':>3}{'рег':>4}{'макс.доля':>10}{'ср.индекс':>10}"
        f"{'Δ к топ':>8}{'цены':>6}{'коорд':>6}"
    )
    print(header)
    for row in scenario_rows:
        print(
            f"{row['scenario_id']:<28}{row['n']:>3}{row['region_count']:>4}"
            f"{row['max_region_share']:>10.2f}{row['avg_index']:>10.1f}{row['avg_index_vs_top']:>8.1f}"
            f"{row['observed_price_count']:>6}{row['confirmed_coords_count']:>6}"
        )
    print(f"Сценариев: {len(scenario_rows)}, курортов в составах: {len(member_rows)}")
    print(f"Сохранено: {scenarios_out}")
    print(f"Сохранено: {members_out}")


if __name__ == "__main__":
    main()

