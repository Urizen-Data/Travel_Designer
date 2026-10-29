#!/usr/bin/env python3
"""Прогноз погоды и оценка состояния трассы (сленг горнолыжников).

Для каждого курорта из data/prepared/resorts.json запрашивает Forecast API
Open-Meteo на 10 дней вперёд и по правилу-эвристике определяет ожидаемое
состояние трассы: «пухляк», «накат», «каша», «лёд» или «без снега».

Правило (пороги заданы константами ниже), результат — «Вероятно …»:
  * нет снега (snow_depth < 0.1 м и снегопад < 3 см)      -> «без снега»;
  * свежий снег >= 10 см и мороз (t_max <= 0°C)           -> «Вероятно пухляк»;
  * оттепель (t_max > 2°C) или дождь (rain >= 1 мм)       -> «Вероятно каша»;
  * цикл таяние/замерзание + тонкий покров (< 0.3 м)      -> «Вероятно лёд»;
  * небольшой свежий снег (>= 3 см) и мороз               -> «Вероятно пухляк»;
  * иначе (без свежего снега)                              -> «Вероятно накат».

Отдельно помечается сильный ветер (порывы >= 50 км/ч).

Результат: data/collected/weather_forecast.json.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PREPARED_DIR = PROJECT_ROOT / "data" / "prepared"
COLLECTED_DIR = PROJECT_ROOT / "data" / "collected"

FORECAST_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "TravelDesignerStudentWorkshop/1.0 open-data-research"
FORECAST_DAYS = 10

DAILY_VARS = (
    "snowfall_sum,rain_sum,temperature_2m_max,temperature_2m_min,"
    "weather_code,wind_speed_10m_max,wind_gusts_10m_max"
)
HOURLY_VARS = "snow_depth,freezing_level_height"

# Пороги правила оценки состояния трассы
SNOW_POWDER_CM = 10.0
SNOW_LIGHT_CM = 3.0
RAIN_SLUSH_MM = 1.0
T_SLUSH_C = 2.0
T_ICE_MIN_C = -2.0
SNOW_DEPTH_BASE_M = 0.1
SNOW_DEPTH_THIN_M = 0.3
WIND_STRONG_KMH = 50.0


def request_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    throttle: float = 0.5,
    attempts: int = 4,
    timeout: int = 120,
) -> Any:
    if params:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{urllib.parse.urlencode(params)}"
    time.sleep(throttle)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
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


def load_resorts() -> list[dict[str, Any]]:
    return json.loads((PREPARED_DIR / "resorts.json").read_text(encoding="utf-8"))


def classify_slope(
    snowfall: float | None,
    rain: float | None,
    t_max: float | None,
    t_min: float | None,
    snow_depth: float | None,
) -> str:
    """Оценить погодные предпосылки состояния трассы (мягкая формулировка).

    Возвращает категорию, а не фактическое состояние поверхности: дневные
    min/max не фиксируют последовательность оттепели и замерзания, а нулевой
    модельный покров не учитывает искусственное оснежение (ТЗ дашборда §5.3).
    """
    return classify_slope_explained(snowfall, rain, t_max, t_min, snow_depth)[0]


def classify_slope_explained(
    snowfall: float | None,
    rain: float | None,
    t_max: float | None,
    t_min: float | None,
    snow_depth: float | None,
) -> tuple[str, str, str]:
    """Вернуть (категория, причина, ограничение) для состояния трассы.

    Приоритет правил:
      1) нет естественного покрова: depth < 0.1 м и снегопад < 3 см;
      2) свежий рыхлый снег:      снегопад >= 3 см и t_max <= 0°C;
      3) увлажнение/размягчение:  дождь >= 1 мм или оттепель (t_max > 2°C);
      4) замерзание:              суточный ход t_min <= -2 и t_max > 0 при
                                  тонком покрове (< 0.3 м);
      5) иначе: оценки недостаточно.
    """
    snow = snowfall if snowfall is not None else 0.0
    depth = snow_depth if snow_depth is not None else 0.0
    tmax = t_max if t_max is not None else 0.0
    tmin = t_min if t_min is not None else 0.0
    rn = rain if rain is not None else 0.0

    if depth < SNOW_DEPTH_BASE_M and snow < SNOW_LIGHT_CM:
        return (
            "модель не показывает естественный снежный покров",
            f"модельная высота снега {depth:.2f} м и снегопад {snow:.0f} см",
            "не учитывает искусственное оснежение",
        )
    if snow >= SNOW_LIGHT_CM and tmax <= 0:
        return (
            "предпосылки свежего рыхлого снега",
            f"снегопад {snow:.0f} см при t_max {tmax:.0f}°C",
            "оценка по дневным данным, не фактическая поверхность",
        )
    if rn >= RAIN_SLUSH_MM or tmax > T_SLUSH_C:
        trigger = f"дождь {rn:.0f} мм" if rn >= RAIN_SLUSH_MM else f"оттепель (t_max {tmax:.0f}°C)"
        return (
            "предпосылки увлажнения/размягчения",
            trigger,
            "не фактическое состояние подготовленной трассы",
        )
    if tmax > 0 and tmin < T_ICE_MIN_C and depth < SNOW_DEPTH_THIN_M:
        return (
            "предпосылки замерзания",
            f"суточный ход температуры {tmin:.0f}…{tmax:.0f}°C при тонком покрове",
            "дневные min/max не фиксируют точную последовательность оттепели и замерзания",
        )
    return (
        "оценки недостаточно",
        "нет выраженных признаков свежего снега, осадков или замерзания",
        "по дневным данным нельзя оценить состояние поверхности",
    )


def _daily_from_hourly(values: list[Any] | None, i: int, agg: str) -> float | None:
    if not values:
        return None
    chunk = [v for v in values[i * 24 : i * 24 + 24] if v is not None]
    if not chunk:
        return None
    return max(chunk) if agg == "max" else min(chunk)


def fetch_resort(resort: dict[str, Any]) -> dict[str, Any]:
    """Прогноз на 7 дней для одного курорта."""
    params = {
        "latitude": resort["latitude"],
        "longitude": resort["longitude"],
        "forecast_days": FORECAST_DAYS,
        "daily": DAILY_VARS,
        "hourly": HOURLY_VARS,
        "timezone": "Europe/Moscow",  # единая ось дат для всех курортов (иначе timezone=auto даёт 8 дат)
    }
    payload = request_json(FORECAST_ENDPOINT, params=params)
    daily = payload.get("daily", {})
    hourly = payload.get("hourly", {})
    elevation = payload.get("elevation")

    snow_depth_h = hourly.get("snow_depth", [])
    freezing_level_h = hourly.get("freezing_level_height", [])

    days: list[dict[str, Any]] = []
    for i, date in enumerate(daily.get("time", [])[:FORECAST_DAYS]):
        snowfall = daily.get("snowfall_sum", [None])[i]
        rain = daily.get("rain_sum", [None])[i]
        t_max = daily.get("temperature_2m_max", [None])[i]
        t_min = daily.get("temperature_2m_min", [None])[i]
        wc = daily.get("weather_code", [None])[i]
        wind_gust = daily.get("wind_gusts_10m_max", [None])[i]
        snow_depth = _daily_from_hourly(snow_depth_h, i, "max")
        freezing_level = _daily_from_hourly(freezing_level_h, i, "min")

        condition = classify_slope(snowfall, rain, t_max, t_min, snow_depth)
        days.append(
            {
                "date": date,
                "snowfall_cm": snowfall,
                "rain_mm": rain,
                "temperature_min_c": t_min,
                "temperature_max_c": t_max,
                "weather_code": wc,
                "wind_gusts_max_kmh": wind_gust,
                "snow_depth_m": snow_depth,
                "freezing_level_min_m": freezing_level,
                "slope_condition": condition,
                "strong_wind": (wind_gust or 0) >= WIND_STRONG_KMH,
            }
        )
    return {
        "resort_id": resort["resort_id"],
        "name_ru": resort["name_ru"],
        "region": resort["region"],
        "latitude": resort["latitude"],
        "longitude": resort["longitude"],
        "elevation_m": elevation,
        "resort_elevation_m": resort.get("open_meteo_elevation_m"),
        "days": days,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="только первые N курортов")
    parser.add_argument("--resort", type=str, default="", help="resort_id через запятую")
    args = parser.parse_args()

    resorts = load_resorts()
    if args.resort:
        wanted = {s.strip() for s in args.resort.split(",") if s.strip()}
        resorts = [r for r in resorts if r["resort_id"] in wanted]
    if args.limit:
        resorts = resorts[: args.limit]

    print(f"Прогноз для {len(resorts)} курортов на {FORECAST_DAYS} дней ...", flush=True)
    results: list[dict[str, Any]] = []
    for i, resort in enumerate(resorts, start=1):
        print(f"[{i}/{len(resorts)}] {resort['resort_id']} {resort['name_ru']}", flush=True)
        try:
            results.append(fetch_resort(resort))
        except Exception as exc:  # noqa: BLE001
            print(f"  ОШИБКА {resort['resort_id']}: {type(exc).__name__}", flush=True)
            results.append(
                {"resort_id": resort["resort_id"], "name_ru": resort["name_ru"],
                 "error": str(exc)}
            )

    COLLECTED_DIR.mkdir(parents=True, exist_ok=True)
    out = COLLECTED_DIR / "weather_forecast.json"
    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "forecast_days": FORECAST_DAYS,
        "rule": {
            "SNOW_POWDER_CM": SNOW_POWDER_CM,
            "SNOW_LIGHT_CM": SNOW_LIGHT_CM,
            "RAIN_SLUSH_MM": RAIN_SLUSH_MM,
            "T_SLUSH_C": T_SLUSH_C,
            "T_ICE_MIN_C": T_ICE_MIN_C,
            "SNOW_DEPTH_BASE_M": SNOW_DEPTH_BASE_M,
            "SNOW_DEPTH_THIN_M": SNOW_DEPTH_THIN_M,
            "WIND_STRONG_KMH": WIND_STRONG_KMH,
        },
        "resorts": results,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Сохранено: {out}")


if __name__ == "__main__":
    main()
