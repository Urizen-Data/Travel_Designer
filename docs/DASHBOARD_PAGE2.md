# Страница 2 «Факты и сравнение» — финальный план (консолидированный)

> Сводка решений четырёх участников (заказчик + Cline + Astra + DeepSeek). Спорные моменты решены, критический приоритет — за Cline (есть доступ ко всем данным).

## 0. Решения по спорным моментам

| Вопрос | Решение |
|---|---|
| Архитектура данных | **Не трогаем `atlas_ratings`** (54 колонки, нужна Странице 1). Для Страницы 2 — **3 SQL view** + существующие таблицы. |
| «Сейчас на склоне» | `ORDER BY date ASC LIMIT 1` (ранний день прогноза = сегодня). Подпись **«Прогноз на {дата}»**, не «сейчас». |
| Вклады индекса | **Горизонтальные полосы** (не Donut). Датасет `resort_components`. |
| Инфраструктура | **Горизонтальные полосы** (не Treemap, не Grouped). |
| Геометрия + типы трасс | **Одна Handlebars-карточка** (объединены). |
| `confidence_score` | «Качество данных: N / 100» — балл, **не** «уверенность %». |
| Высоты | Перепад = `max − min`. Полоса: смещение = min, длина = max − min. |
| Шкалы осей | Одинаковые пределы во всех трёх колонках. |
| Прогноз в карточке | Все погодные поля — из **одной строки** (LATERAL join). |

---

## 1. Назначение и смысловая нить

**Название:** «Факты и сравнение». **Главный вопрос:** чем отличаются выбранные курорты по катанию, инфраструктуре и погодным условиям?

```text
Краткая сводка → Вклады индекса → Масштаб/высоты/типы → Сложность → Инфраструктура → Климат → Прогноз
```

Индекс на странице — **базовый** (`preset_id = 'base'`).

---

## 2. Сетка и итоговая структура (7 рядов)

Три колонки по 4 единицы из 12. Строим рядами (одинаковые блоки — на одной высоте).

| # | Ряд | Визуализация | Датасет | Высота |
|---|---|---|---|---|
| — | Фильтры | 3 × Native Filter `name_ru` (single) | — | — |
| 1 | **Краткая сводка** | Handlebars | `v_compare_summary` | 340–400 px |
| 2 | Вклады в базовый индекс | Горизонтальный Bar (5) | `resort_components` | 230–270 px |
| 3 | Масштаб, высоты и типы | Handlebars (цифры + бейджи) | `v_compare_summary` | 200–250 px |
| 4 | Структура сложности | Горизонтальный Bar (7, доли %) | `v_compare_difficulty` | 260–300 px |
| 5 | Инфраструктура вокруг | Горизонтальный Bar (4) | `v_compare_infrastructure` | 250–290 px |
| 6 | Исторический климат (ноябрь–апрель) | Mixed Time-series | `climate_monthly` | 280–330 px |
| 7 | Прогноз на ближайшие дни | Mixed Time-series | `weather_forecast_daily` | 300–350 px |

Итого **7 рядов × 3 колонки = 21 чарт** + 3 фильтра + Markdown-оговорки.

---

## 3. Ряд 1 — Краткая сводка (Handlebars)

**Состав карточки:** имя, регион, базовый индекс + место, качество данных, цена + продукт/сезон, прогноз на дату, сильные/ограничения, аэропорт, ссылки.

```handlebars
{{#each data}}
<div style="font-family:Segoe UI,sans-serif;background:#17262E;color:#F5F7F8;border-radius:8px;padding:14px;display:flex;flex-direction:column;gap:8px;height:100%;box-sizing:border-box;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;">
    <div>
      <div style="font-size:20px;font-weight:700;color:#93B9C6;">{{ name_ru }}</div>
      <div style="font-size:12px;color:#C2D8DF;">{{ region }}</div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:22px;font-weight:700;">{{ index_score }}</div>
      <div style="font-size:10px;color:#93B9C6;">Индекс · место {{ index_rank }}</div>
    </div>
  </div>

  <div style="font-size:12px;color:#C2D8DF;">Качество данных: {{ quality_score }} / 100</div>

  <div style="background:rgba(147,185,198,.15);padding:6px 8px;border-radius:4px;font-size:12px;">
    💰 {{ price_rub }} ₽ · {{ price_product }}<br><span style="color:#C2D8DF;">{{ price_season }}</span>
  </div>

  <div style="background:rgba(169,112,91,.2);padding:6px 8px;border-radius:4px;font-size:12px;">
    🏔 Прогноз на {{ forecast_date }}: {{ forecast_condition }} · снег {{ forecast_snow_depth_m }} м · {{ forecast_temp_min_c }}…{{ forecast_temp_max_c }} °C
  </div>

  {{#if strengths_text}}<div style="font-size:12px;color:#93B9C6;">▲ {{ strengths_text }}</div>{{/if}}
  {{#if weaknesses_text}}<div style="font-size:12px;color:#B79B72;">▼ {{ weaknesses_text }}</div>{{/if}}

  <div style="font-size:11px;color:#C2D8DF;">Аэропорт: {{ airport_iata }} · {{ airport_km }} км по прямой</div>

  <div style="display:flex;gap:10px;font-size:12px;border-top:1px solid #2E5A5E;padding-top:6px;margin-top:auto;">
    {{#if details_url}}<a href="{{{ details_url }}}" target="_blank" rel="noopener noreferrer" style="color:#93B9C6;">Справка</a>{{/if}}
    {{#if official_website_url}}<a href="{{{ official_website_url }}}" target="_blank" rel="noopener noreferrer" style="color:#93B9C6;">Сайт</a>{{/if}}
    {{#if skimap_url}}<a href="{{{ skimap_url }}}" target="_blank" rel="noopener noreferrer" style="color:#93B9C6;">Карты трасс</a>{{/if}}
    {{#if price_source_url}}<a href="{{{ price_source_url }}}" target="_blank" rel="noopener noreferrer" style="color:#93B9C6;">Источник цены</a>{{/if}}
  </div>
</div>
{{/each}}
```

**Правила подписей:**
- Цена — «средняя наблюдаемая цена дневного ски-пасса за сезон»; без цены — «цена не наблюдалась», не «0 ₽».
- Прогноз — «Прогноз на {дата}», не «сейчас»; устаревший пакет → «Свежий прогноз недоступен. Обновлён {fetched_at}».
- `official_website_url` может быть списком — подставить только первый/проверенный адрес.
- `details_url` без известного типа → «Справка».

---

## 4. Ряды 2–5 — спецификация

**Ряд 2 — Вклады (горизонтальный Bar):**
- Датасет `resort_components`. **Y:** `component_name_ru` (фикс. порядок). **X:** `SUM(contribution)`.
- Шкала X одинаковая (0–40). Подпись: «Вклады в баллы индекса; сумма = индекс».
- Цвета: спрос `#2E5A5E`, инфраструктура `#5E8FA0`, зима `#93B9C6`, доступность `#B79B72`, цена `#A9705B`.

**Ряд 3 — Масштаб, высоты и типы (Handlebars):**
```text
ВЫСОТНЫЙ ДИАПАЗОН
938 — 2 457 м · перепад 1 519 м
89.9 км            N объектов        M линий
нанесённой сети    трасс (источник)  подъёмников
Типы: ✓ Сноупарк · ✓ Беговые · ✓ Прочее
```
- Перепад = `piste_max_elevation_m − piste_min_elevation_m`.
- `piste_ways_total` → «объекты трасс в источнике», не «число трасс».
- Бейджи: `>0` → «Найдено: N», `0` → «Не найдено в источнике», `NULL` → «Нет данных».

**Ряд 4 — Сложность (горизонтальный Bar, доли):**
- Датасет `v_compare_difficulty`. **Y:** `difficulty_name` (7 уровней). **X:** `share_pct`.
- Шкала 0–100%. Категории: novice → easy → intermediate → advanced → expert → freeride → **unknown** (не скрывать).

**Ряд 5 — Инфраструктура (горизонтальный Bar):**
- Датасет `v_compare_infrastructure`. **Y:** `infrastructure_category` (4). **X:** `object_count`.
- Категории: Размещение, Питание, Достопримечательности, Транспорт.

---

## 5. Ряды 6–7 — Климат и прогноз (Mixed Time-series)

**Ряд 6 — Исторический климат:** `climate_monthly`. **X:** `season_axis_date` (техническая дата). **Bar:** `avg_monthly_snowfall_cm` (левая ось). **Line:** `mean_temperature_c` (правая ось). Порядок месяцев ноябрь→апрель. Подпись: «30 сезонов, ERA5, высота {elevation}».

**Ряд 7 — Прогноз:** `weather_forecast_daily`. **X:** `date`. **Bar:** `snowfall_cm`. **Line:** `temperature_min_c` + `temperature_max_c`. Одинаковые пределы осей. Недостающие даты не превращать в нули.

---

## 6. Архитектура датасетов и SQL views

Не трогаем `atlas_ratings`. Для Страницы 2 — **3 view** + существующие таблицы (`resort_components`, `climate_monthly`, `weather_forecast_daily`).

### `v_compare_summary` — одна строка на курорт (карточка + геометрия)

```sql
CREATE OR REPLACE VIEW v_compare_summary AS
SELECT
    rf.resort_id, rf.name_ru, rf.region, rf.latitude, rf.longitude,

    -- Базовый рейтинг (atlas_ratings, preset_id='base')
    ar.base_score AS index_score, ar.base_rank AS index_rank,
    ar.confidence_score AS quality_score,
    ar.coordinate_validation_status, ar.quality_flags,

    -- Цена (resort_features)
    rf.adult_skipass_avg_rub AS price_rub, rf.price_months_count,
    rf.price_product, rf.price_season, rf.price_source_url, rf.price_source_quality,

    -- Аэропорт
    rf.nearest_airport_distance_km AS airport_km, rf.nearest_airport_iata AS airport_iata,

    -- Геометрия и типы
    rf.piste_min_elevation_m, rf.piste_max_elevation_m,
    rf.piste_length_km, rf.piste_ways_total, rf.lift_lines_6km,
    rf.piste_type_snow_park, rf.piste_type_nordic, rf.piste_type_other,
    rf.osm_overlap_warning,

    -- Ссылки
    rf.details_url, rf.details_url_source, rf.official_website_url, rf.skimap_url,

    -- Сильные / ограничения (агрегировано)
    (SELECT string_agg(rr.reason_text, '; ' ORDER BY rr.reason_text)
       FROM resort_reasons rr
      WHERE rr.resort_id = rf.resort_id AND rr.reason_type = 'strength') AS strengths_text,
    (SELECT string_agg(rr.reason_text, '; ' ORDER BY rr.reason_text)
       FROM resort_reasons rr
      WHERE rr.resort_id = rf.resort_id AND rr.reason_type = 'weakness') AS weaknesses_text,

    -- Прогноз (ранний день = сегодня, все поля из ОДНОЙ строки)
    wf.date AS forecast_date, wf.slope_condition AS forecast_condition,
    wf.snow_depth_m AS forecast_snow_depth_m,
    wf.temperature_min_c AS forecast_temp_min_c,
    wf.temperature_max_c AS forecast_temp_max_c,
    wf.fetched_at AS forecast_fetched_at

FROM resort_features rf
JOIN atlas_ratings ar ON ar.resort_id = rf.resort_id AND ar.preset_id = 'base'
LEFT JOIN LATERAL (
    SELECT w.* FROM weather_forecast_daily w
     WHERE w.resort_id = rf.resort_id
     ORDER BY w.date ASC LIMIT 1
) wf ON true;
```

### `v_compare_difficulty` — курорт × уровень сложности (доли)

```sql
CREATE OR REPLACE VIEW v_compare_difficulty AS
WITH t AS (
    SELECT resort_id, name_ru, 'novice' AS difficulty_code, 'Новичок' AS difficulty_name, 1 AS ord, piste_difficulty_novice::numeric AS value FROM resort_features
    UNION ALL SELECT resort_id, name_ru, 'easy', 'Лёгкие', 2, piste_difficulty_easy::numeric FROM resort_features
    UNION ALL SELECT resort_id, name_ru, 'intermediate', 'Средние', 3, piste_difficulty_intermediate::numeric FROM resort_features
    UNION ALL SELECT resort_id, name_ru, 'advanced', 'Сложные', 4, piste_difficulty_advanced::numeric FROM resort_features
    UNION ALL SELECT resort_id, name_ru, 'expert', 'Экспертные', 5, piste_difficulty_expert::numeric FROM resort_features
    UNION ALL SELECT resort_id, name_ru, 'freeride', 'Фрирайд', 6, piste_difficulty_freeride::numeric FROM resort_features
    UNION ALL SELECT resort_id, name_ru, 'unknown', 'Неизвестно', 7, piste_difficulty_unknown::numeric FROM resort_features
)
SELECT resort_id, name_ru, difficulty_code, difficulty_name, ord, value,
       ROUND(100 * value / NULLIF(SUM(value) OVER (PARTITION BY resort_id), 0), 1) AS share_pct
FROM t;
```

### `v_compare_infrastructure` — курорт × категория инфраструктуры

```sql
CREATE OR REPLACE VIEW v_compare_infrastructure AS
SELECT resort_id, name_ru, 'Размещение' AS infrastructure_category, 1 AS ord, lodging_objects_6km AS object_count FROM resort_features
UNION ALL SELECT resort_id, name_ru, 'Питание', 2, food_objects_6km FROM resort_features
UNION ALL SELECT resort_id, name_ru, 'Достопримечательности', 3, attraction_objects_6km FROM resort_features
UNION ALL SELECT resort_id, name_ru, 'Транспорт', 4, transport_objects_6km FROM resort_features;
```

### Климат — порядок месяцев ноябрь→апрель

В виртуальном датасете для `climate_monthly` добавить техническую ось (это **не** год наблюдений):

```sql
make_date(CASE WHEN month >= 11 THEN 2000 ELSE 2001 END, month, 1) AS season_axis_date
```

На оси показывать `month_name_ru`. Отключить относительный временной фильтр («последний год» скроет точки).

---

## 7. Фильтры и Scoping

- **3 Native Filter** `name_ru` (single-select), дефолты: `R001 Роза Хутор`, `R002 Красная Поляна`, `R004 Шерегеш`.
- Каждый фильтр в **Scoping → Apply to specific charts** — только на 7 чартов своей колонки.
- Без каскадной зависимости, без cross-filtering на первой итерации.
- Дубликат курорта в двух колонках допустим (полезно для проверки корректности).
- Страница 1 исключена из scope.

---

## 8. Цветовая схема (палитра дашборда)

- Фон страницы `#F5F7F8`; текст `#26303A`; вторичный `#5C6B78`; границы `#DDE5E9`.
- Компоненты индекса: спрос `#2E5A5E`, инфраструктура `#5E8FA0`, зима `#93B9C6`, доступность `#B79B72`, цена `#A9705B`.
- Карточка (тёмная): фон `#17262E`, текст `#F5F7F8`, вторичный `#C2D8DF`, акцент `#93B9C6`, маркер `#A9705B`.
- Сложность — последовательная «Терракота-Небо» (7 оттенков) или монохром.
- Климат/прогноз: температура `#A9705B` (линия), снегопад `#93B9C6` (столбцы).
- Без случайных зелёных/красных; цвет не единственный носитель смысла.

---

## 9. Оговорки (Markdown в подвале)

- OSM-сегменты ≠ официальные километры трасс; сложность — по тегам `piste:difficulty`.
- Климат ERA5 — модельный (~25 км), приведён к средней высоте склона; не метеостанция.
- Расстояние до аэропорта — по прямой, не время трансфера.
- `slope_condition` не учитывает искусственное оснежение.
- Устойчивость/сценарии — не доверительный интервал.

---

## 10. Критерии приёмки

- каждый фильтр меняет только свою колонку; в карточке всегда один курорт;
- карточка и вклады показывают базовую версию; пять вкладов складываются в индекс;
- цена не «0 ₽», если данных нет; качество — «N/100», не «%»;
- перепад высот = `max − min`; сложность `unknown` видна;
- месяцы ноябрь→апрель; прогноз из актуального пакета с явными датами;
- просроченный прогноз не называется текущим; ссылки соответствуют типам;
- три одинаковых графика — одинаковые шкалы; Page 1 не задета фильтрами.

---

## 11. Порядок реализации

1. Проверить схему БД (имена полей, типы, пакеты прогноза, формат ссылок).
2. Создать 3 view (`v_compare_summary`, `v_compare_difficulty`, `v_compare_infrastructure`) + виртуальный датасет климата.
3. Собрать **колонку A** (7 чартов) и выверить подписи/шкалы.
4. Задать единые масштабы и цвета.
5. Скопировать чарты для B и C (отдельные сохранённые ID).
6. Создать 3 фильтра и настроить scoping.
7. Собрать сетку рядами, выровнять высоты, добавить заголовки и оговорки.
8. Проверить на трёх контрастных курортах (крупный / небольшой / с неполными данными).
9. Проверить обновление прогноза (не застревает в кэше статических фактов).

**Итог:** 3 фильтра, 7 рядов, 21 чарт, 3 SQL view. Базовая версия рейтинга, горизонтальные полосы для сравнения, одинаковые шкалы, минимальные изменения существующей архитектуры.



