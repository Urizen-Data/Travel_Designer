#!/usr/bin/env python3
"""Сценарные пресеты скоринга: перевзвешивание 5 компонентных баллов.

Читает 5 компонентных баллов (regional/infrastructure/winter/accessibility/price)
из data/mart/resort_scores.csv, применяет веса пресетов из
data/reference/scoring_presets.json и пишет две витрины:

  * data/mart/presets.csv                  — словарь пресетов (id + название + веса);
  * data/mart/resort_preset_components.csv — long: пресет × курорт × компонент.

Формула: scenario_score = Σ component_score × component_weight_pct / 100.
13 исходных показателей, их нормализация и внутренние веса компонентов НЕ меняются —
меняются только 5 коэффициентов итоговой суммы.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.common.mart_io import read_csv, write_csv  # noqa: E402

MART = PROJECT_ROOT / "data" / "mart"
REFERENCE = PROJECT_ROOT / "data" / "reference"

COMPONENTS = ("regional", "infrastructure", "winter", "accessibility", "price")


def load_config() -> dict[str, Any]:
    return json.loads((REFERENCE / "scoring_presets.json").read_text(encoding="utf-8"))


def validate_config(config: dict[str, Any]) -> None:
    components = tuple(config.get("components") or COMPONENTS)
    assert set(components) == set(COMPONENTS), "components должны быть ровно 5"
    presets = config["presets"]
    for p in presets:
        w = p["weights"]
        assert set(w) == set(COMPONENTS), f"{p['preset_id']}: неполный набор весов"
        assert abs(sum(float(w[c]) for c in COMPONENTS) - 100.0) <= 0.01, (
            f"{p['preset_id']}: сумма весов != 100"
        )
    ids = [p["preset_id"] for p in presets]
    assert len(ids) == len(set(ids)), "preset_id не уникальны"
    assert "base" in ids, "нужен пресет 'base'"


def build_preset_tables() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    config = load_config()
    validate_config(config)

    names_ru = config.get("component_names_ru") or {}
    version = config.get("analysis_version") or "v1"

    scores = {r["resort_id"]: r for r in read_csv(MART / "resort_scores.csv")}
    features = {r["resort_id"]: r for r in read_csv(MART / "resort_features.csv")}

    preset_rows: list[dict[str, Any]] = []
    component_rows: list[dict[str, Any]] = []

    for preset in config["presets"]:
        preset_id = preset["preset_id"]
        weights = {c: float(preset["weights"][c]) for c in COMPONENTS}

        preset_rows.append(
            {
                "preset_id": preset_id,
                "name_ru": preset.get("name_ru", preset_id),
                "description": preset.get("description", ""),
                **{f"{c}_weight": weights[c] for c in COMPONENTS},
            }
        )

        scored = []
        for rid, s in scores.items():
            score = sum(float(s[c + "_score"]) * weights[c] / 100.0 for c in COMPONENTS)
            scored.append((rid, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        scenario_rank = {rid: i + 1 for i, (rid, _) in enumerate(scored)}
        scenario_score_by_rid = dict(scored)

        for rid, s in scores.items():
            scenario_score = scenario_score_by_rid[rid]
            base_rank = int(s["rank"])
            has_price = features.get(rid, {}).get("adult_skipass_avg_rub") is not None
            for c in COMPONENTS:
                comp_score = float(s[c + "_score"])
                component_rows.append(
                    {
                        "analysis_version": version,
                        "preset_id": preset_id,
                        "resort_id": rid,
                        "component": c,
                        "component_name_ru": names_ru.get(c, c),
                        "component_score": comp_score,
                        "component_weight_pct": weights[c],
                        "contribution": comp_score * weights[c] / 100.0,
                        "scenario_score": scenario_score,
                        "scenario_rank": scenario_rank[rid],
                        "base_score": float(s["popularity_score"]),
                        "base_rank": base_rank,
                        "rank_change": base_rank - scenario_rank[rid],
                        "has_observed_price": has_price,
                    }
                )

    return preset_rows, component_rows


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    preset_rows, component_rows = build_preset_tables()

    write_csv(MART / "presets.csv", preset_rows)
    write_csv(MART / "resort_preset_components.csv", component_rows)

    print(f"presets.csv: {len(preset_rows)} пресетов")
    print(
        f"resort_preset_components.csv: {len(component_rows)} строк "
        f"({len(preset_rows)} пресетов × {len(COMPONENTS)} компонентов)"
    )


if __name__ == "__main__":
    main()
