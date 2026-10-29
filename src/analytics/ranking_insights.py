#!/usr/bin/env python3
"""Аналитическая витрина: компоненты, локальный рейтинг и устойчивость.

Считает поверх data/mart/resort_scores.csv (готовые 13 нормированных баллов),
без нового сбора данных.

1. Пять компонентных баллов (0–100) — взвешенная средняя баллов внутри компонента:
   * Региональный спрос (40)  = поездки 25 + рост 10 + длительность 5;
   * Инфраструктура (25)      = трассы 10 + подъёмники 7 + размещение 5 + питание 3;
   * Зимние условия (20)      = снежные дни 8 + морозные 6 + снегопад 6;
   * Доступность (10)         = аэропорт 8 + транспорт 2;
   * Цена (5)                 = ски-пасс 5.

2. Вклад компонента в итоговый индекс = компонентный_балл × (вес / 100).
   Сумма пяти вкладов равна popularity_score (проверяется).

3. Локальный рейтинг без регионального блока — для каждого пресета:
       local_score = Σ (балл_компонента × вес_пресета) / Σ вес_пресета
                     по 4 нерегиональным компонентам (infra, winter, access, price),
                     с перенормировкой к 100%. Региональный компонент не участвует.
       local_rank = место по local_score внутри пресета.

4. Устойчивость к весам (Монте-Карло) — для каждого из 6 пресетов:
   варьируем веса 5 компонентов мультипликативным шумом ×U(0.6, 1.4) вокруг
   весов ЭТОГО пресета, затем перенормировка к сумме 100. Фиксированный seed
   → детерминизм. Для каждого (курорт × пресет): медианное место, 5-й/95-й
   процентили места, частота попадания в топ-10.

Интервал мест обозначаем как «диапазон мест в сценариях весов», а не как
доверительный интервал качества курорта.

Выход:
  * data/mart/resort_components.csv — длинный формат (курорт × компонент);
  * data/mart/ranking_stability.csv — плоский (курорт × пресет × метрики);
  * data/mart/resort_reasons.csv    — объяснения «почему» (длинный формат).
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

MART = PROJECT_ROOT / "data" / "mart"
ANALYTICS = MART

from src.common.mart_io import read_csv, write_csv  # noqa: E402

# Порядок компонентов фиксирует позиции весов во всех векторах ниже.
COMPONENT_ORDER: tuple[str, ...] = (
    "regional",
    "infrastructure",
    "winter",
    "accessibility",
    "price",
)

COMPONENT_NAMES_RU: dict[str, str] = {
    "regional": "Региональный спрос",
    "infrastructure": "Инфраструктура",
    "winter": "Зимние условия",
    "accessibility": "Доступность",
    "price": "Цена",
}

# Тексты сильных сторон для шаблонных объяснений «почему».
STRENGTH_TEXTS: dict[str, str] = {
    "regional": "Высокий региональный турпоток",
    "infrastructure": "Развитая инфраструктура (по OSM в радиусе 6 км)",
    "winter": "Надёжные зимние условия по климатическим данным",
    "accessibility": "Удобная доступность (близкий аэропорт)",
    "price": "Доступная цена ски-пасса среди наблюдаемых",
}

# Верхняя/нижняя квартиль (топ-8 и худшие-8 из 32) для сильных/слабых сторон.
TOP_QUARTILE_COUNT = 8

# Компонент: общий вес (сумма = 100) и под-баллы с весами внутри компонента.
COMPONENTS: dict[str, dict[str, Any]] = {
    "regional": {
        "weight": 40.0,
        "subscores": [("region_trips", 25.0), ("region_growth", 10.0), ("avg_stay", 5.0)],
    },
    "infrastructure": {
        "weight": 25.0,
        "subscores": [("pistes", 10.0), ("lifts", 7.0), ("lodging", 5.0), ("amenities", 3.0)],
    },
    "winter": {
        "weight": 20.0,
        "subscores": [("snow_days", 8.0), ("freezing_days", 6.0), ("snowfall", 6.0)],
    },
    "accessibility": {
        "weight": 10.0,
        "subscores": [("airport", 8.0), ("transport", 2.0)],
    },
    "price": {
        "weight": 5.0,
        "subscores": [("price", 5.0)],
    },
}

# Параметры Монте-Карло: мультипликативный шум ×U(0.6, 1.4) вокруг весов пресета,
# затем перенормировка к сумме 100. Фиксированный seed → детерминизм.
N_SIMULATIONS = 5000
SEED = 42
NOISE_MIN = 0.6
NOISE_MAX = 1.4

# Компоненты локального рейтинга (без регионального).
LOCAL_COMPONENTS = ("infrastructure", "winter", "accessibility", "price")


# Сырые поля из resort_features, нужные для причин и признака «есть цена».
RAW_FIELDS = ("adult_skipass_avg_rub", "coordinate_status", "quality_flags", "completeness_pct")


def load_scores() -> list[dict[str, Any]]:
    """resort_scores.csv + сырые поля из resort_features.csv (по resort_id)."""
    scores = read_csv(MART / "resort_scores.csv")
    features = read_csv(MART / "resort_features.csv")
    by_id = {f["resort_id"]: f for f in features}
    for r in scores:
        f = by_id.get(r["resort_id"], {})
        for field in RAW_FIELDS:
            r[field] = f.get(field)
    return scores


def load_presets() -> list[dict[str, Any]]:
    """presets.csv — 6 пресетов (preset_id + name_ru + 5 весов) в порядке файла."""
    return read_csv(MART / "presets.csv")


def has_observed_price(row: dict[str, Any]) -> bool:
    return row.get("adult_skipass_avg_rub") is not None


def component_score(row: dict[str, Any], comp: str) -> float:
    """Компонентный балл 0–100 как взвешенная средняя под-баллов."""
    cfg = COMPONENTS[comp]
    total = sum(float(row[key + "_score"]) * weight for key, weight in cfg["subscores"])
    return total / cfg["weight"]


def contributions(row: dict[str, Any]) -> dict[str, float]:
    """Вклады компонентов в итоговый индекс (в пунктах, сумма = popularity_score)."""
    result: dict[str, float] = {}
    for comp in COMPONENT_ORDER:
        score = component_score(row, comp)
        result[comp] = score * COMPONENTS[comp]["weight"] / 100.0
    return result


def rank_by_scores(score_by_id: dict[str, float]) -> dict[str, int]:
    """Место (1..N) по убыванию балла; при равенстве — по resort_id."""
    ordered = sorted(score_by_id.items(), key=lambda kv: (-kv[1], kv[0]))
    return {rid: rank for rank, (rid, _) in enumerate(ordered, start=1)}


def percentile_nearest(sorted_values: list[int], q: float) -> int:
    """Процентиль по ближайшему рангу (nearest-rank)."""
    n = len(sorted_values)
    rank = max(1, min(n, math.ceil(q / 100.0 * n)))
    return sorted_values[rank - 1]


def build_component_rows(scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Длинный формат: курорт × компонент (для накопленных столбцов)."""
    rows: list[dict[str, Any]] = []
    for r in scores:
        for comp in COMPONENT_ORDER:
            cfg = COMPONENTS[comp]
            score = component_score(r, comp)
            rows.append(
                {
                    "resort_id": r["resort_id"],
                    "name_ru": r["name_ru"],
                    "region": r["region"],
                    "component": comp,
                    "component_name_ru": COMPONENT_NAMES_RU[comp],
                    "component_weight": cfg["weight"],
                    "component_score": round(score, 2),
                    "contribution": round(score * cfg["weight"] / 100.0, 4),
                }
            )
    return rows


def build_stability_rows(scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Плоский формат: курорт × пресет × метрики устойчивости и локального рейтинга."""
    presets = load_presets()
    comp_scores = {
        r["resort_id"]: {c: component_score(r, c) for c in COMPONENT_ORDER} for r in scores
    }
    by_resort = sorted(scores, key=lambda r: r["resort_id"])

    rows: list[dict[str, Any]] = []
    for p in presets:
        preset_id = p["preset_id"]
        preset_name = p["name_ru"]
        weights = [float(p[f"{c}_weight"]) for c in COMPONENT_ORDER]

        # Монте-Карло вокруг весов ЭТОГО пресета. Пере-сид на каждый пресет, чтобы
        # base-пресет давал те же значения, что и раньше (тот же seed + те же веса).
        rng = random.Random(SEED)
        rank_lists: dict[str, list[int]] = {r["resort_id"]: [] for r in scores}
        for _ in range(N_SIMULATIONS):
            noisy = [w * rng.uniform(NOISE_MIN, NOISE_MAX) for w in weights]
            total = sum(noisy)
            wts = [w / total * 100.0 for w in noisy]
            score_by_id = {
                r["resort_id"]: sum(
                    comp_scores[r["resort_id"]][c] * w for c, w in zip(COMPONENT_ORDER, wts)
                ) / 100.0
                for r in scores
            }
            ranks = rank_by_scores(score_by_id)
            for rid, rank in ranks.items():
                rank_lists[rid].append(rank)

        # Локальный рейтинг без регионального блока: взвешенная сумма 4 компонентов
        # с весами пресета, перенормированная к 100%.
        local_total = sum(float(p[f"{c}_weight"]) for c in LOCAL_COMPONENTS)
        local_scores: dict[str, float] = {
            r["resort_id"]: sum(
                comp_scores[r["resort_id"]][c] * float(p[f"{c}_weight"])
                for c in LOCAL_COMPONENTS
            ) / local_total
            for r in scores
        }
        local_ranks = rank_by_scores(local_scores)

        for r in by_resort:
            rid = r["resort_id"]
            ranks = sorted(rank_lists[rid])
            rows.append(
                {
                    "resort_id": rid,
                    "preset_id": preset_id,
                    "preset_name_ru": preset_name,
                    "name_ru": r["name_ru"],
                    "region": r["region"],
                    "median_rank": percentile_nearest(ranks, 50),
                    "rank_p5": percentile_nearest(ranks, 5),
                    "rank_p95": percentile_nearest(ranks, 95),
                    "top10_frequency": round(sum(1 for x in ranks if x <= 10) / len(ranks), 4),
                    "local_score": round(local_scores[rid], 2),
                    "local_rank": local_ranks[rid],
                }
            )
    return rows


def build_reason_rows(scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Шаблонные объяснения «почему»: сильные стороны, что проверить, компромисс."""
    comp = {
        r["resort_id"]: {c: component_score(r, c) for c in COMPONENT_ORDER} for r in scores
    }
    top_ids: dict[str, set[str]] = {}
    bottom_ids: dict[str, set[str]] = {}
    for c in COMPONENT_ORDER:
        ordered = sorted(comp, key=lambda rid: -comp[rid][c])
        top_ids[c] = set(ordered[:TOP_QUARTILE_COUNT])
        bottom_ids[c] = set(ordered[-TOP_QUARTILE_COUNT:])

    rows: list[dict[str, Any]] = []
    for r in scores:
        rid = r["resort_id"]
        strengths = [
            c
            for c in COMPONENT_ORDER
            if rid in top_ids[c] and (c != "price" or has_observed_price(r))
        ]
        weaknesses = [c for c in COMPONENT_ORDER if rid in bottom_ids[c]]

        reasons: list[dict[str, str]] = []
        for c in strengths:
            reasons.append({"type": "strength", "code": f"strong_{c}", "text": STRENGTH_TEXTS[c]})

        if not has_observed_price(r):
            reasons.append(
                {"type": "caveat", "code": "no_price", "text": "Цена ски-пасса не собрана"}
            )
        if r.get("coordinate_status") == "needs_review":
            reasons.append(
                {"type": "caveat", "code": "coords_review", "text": "Координаты требуют проверки"}
            )
        if r.get("quality_flags"):
            reasons.append(
                {"type": "caveat", "code": "quality_flags", "text": f"Флаги качества: {r['quality_flags']}"}
            )
        completeness = r.get("completeness_pct")
        if completeness is not None and completeness < 0.9:
            reasons.append(
                {"type": "caveat", "code": "incomplete", "text": f"Данные неполны (полнота {int(completeness * 100)}%)"}
            )
        if strengths and weaknesses:
            reasons.append(
                {
                    "type": "tradeoff",
                    "code": "tradeoff",
                    "text": f"Компромисс: сильная сторона — {COMPONENT_NAMES_RU[strengths[0]]}, "
                    f"слабая — {COMPONENT_NAMES_RU[weaknesses[0]]}",
                }
            )

        rows.append({"resort_id": rid, "name_ru": r["name_ru"], "reasons": reasons})
    return rows


def validate(scores: list[dict[str, Any]], stability: list[dict[str, Any]]) -> None:
    n = len(scores)
    presets = load_presets()
    n_presets = len(presets)
    expected = n * n_presets
    assert len(stability) == expected, (
        f"ожидалось {n}×{n_presets}={expected} строк, получено {len(stability)}"
    )
    keys = [(r["resort_id"], r["preset_id"]) for r in stability]
    assert len(set(keys)) == expected, "пары (resort_id, preset_id) не уникальны"

    # Базовая модель обязана воспроизводить popularity_score из resort_scores.csv.
    base_weights = [COMPONENTS[c]["weight"] for c in COMPONENT_ORDER]
    for r in scores:
        score = sum(
            component_score(r, c) * w for c, w in zip(COMPONENT_ORDER, base_weights)
        ) / 100.0
        assert abs(score - float(r["popularity_score"])) <= 1e-3, (
            f"{r['resort_id']}: базовый балл {score:.4f} != popularity {r['popularity_score']}"
        )

    for row in stability:
        assert 1 <= row["rank_p5"] <= n, row
        assert 1 <= row["median_rank"] <= n, row
        assert 1 <= row["rank_p95"] <= n, row
        assert row["rank_p5"] <= row["median_rank"] <= row["rank_p95"], row
        assert 0.0 <= row["top10_frequency"] <= 1.0, row
        assert 0.0 <= row["local_score"] <= 100.0, row
        assert 1 <= row["local_rank"] <= n, row


def validate_reasons(reason_rows: list[dict[str, Any]]) -> None:
    assert len({r["resort_id"] for r in reason_rows}) == len(reason_rows), "resort_id причин не уникальны"
    valid_types = {"strength", "caveat", "tradeoff"}
    for row in reason_rows:
        for reason in row["reasons"]:
            assert reason["type"] in valid_types, f"{row['resort_id']}: тип {reason['type']}"
            assert reason["code"], f"{row['resort_id']}: пустой code"
            assert reason["text"], f"{row['resort_id']}: пустой text"


def _configure_stdout() -> None:
    """UTF-8 для вывода, иначе символы вроде Δ/× падают в консоли cp1251."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main() -> None:
    _configure_stdout()
    scores = load_scores()
    component_rows = build_component_rows(scores)
    stability = build_stability_rows(scores)
    reason_rows = build_reason_rows(scores)
    validate(scores, stability)
    validate_reasons(reason_rows)

    ANALYTICS.mkdir(parents=True, exist_ok=True)

    components_out = ANALYTICS / "resort_components.csv"
    write_csv(components_out, component_rows)

    stability_out = ANALYTICS / "ranking_stability.csv"
    write_csv(stability_out, stability)

    # reasons: разворачиваем вложенный список причин в длинный формат (одна строка = причина)
    reason_flat = []
    for row in reason_rows:
        for reason in row["reasons"]:
            reason_flat.append(
                {
                    "resort_id": row["resort_id"],
                    "name_ru": row["name_ru"],
                    "reason_type": reason["type"],
                    "reason_code": reason["code"],
                    "reason_text": reason["text"],
                }
            )
    reasons_out = ANALYTICS / "resort_reasons.csv"
    write_csv(reasons_out, reason_flat)

    presets = load_presets()
    print(f"resort_components: {len(component_rows)} строк")
    print(f"ranking_stability: {len(stability)} строк ({len(presets)} пресетов × {len(scores)} курортов)")
    print(f"resort_reasons: {len(reason_flat)} строк")
    print(f"Сохранено: {components_out}")
    print(f"Сохранено: {stability_out}")
    print(f"Сохранено: {reasons_out}")


if __name__ == "__main__":
    main()
