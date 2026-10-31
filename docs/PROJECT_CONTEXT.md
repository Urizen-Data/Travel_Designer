# Полный контекст проекта Travel Designer (SKI ATLAS)

> Исчерпывающее описание данных, их слоёв, источников, скриптов, режимов пайплайна, каскадов сбора, инкрементальности, кэширования и отличий от исходного ТЗ.
> Дополняет `README.md` (обзор) и является «глубоким погружением» для аналитика/разработчика.

## 1. Что это и зачем

**Ski Atlas** — воспроизводимый композитный рейтинг **32 горнолыжных курортов в 20 регионах РФ** для приоритизации подключения к каталогу Travel Designer. Прямой сопоставимой статистики посещаемости нет, поэтому рейтинг собирается из открытых источников (турпоток, OSM, климат, аэропорт, цены) и превращается в **объяснимый индекс** с оценкой уверенности и устойчивости.

Ключевая идея — не «правильный ответ», а **прозрачный и воспроизводимый инструмент**: 13 показателей → 5 компонентов → индекс, с весами в JSON-конфигах, drill-down до сырых фактов и честными ограничениями.

## 2. Полная карта источников

| Источник | Тип | Что отдаёт | Скрипт | Слой |
|---|---|---|---|---|
| **OpenSkiMap** | API (skiArea) | Готовые координаты skiArea, трассы, подъёмники, сложность, высоты, типы трасс | `geocode_resorts`, `recompute_resort_data` | Collected / Prepared |
| **Wikidata** | API | Q-id, координаты P625, sitelink Wikipedia, P6400 (Skimap ID) | `geocode_resorts`, `fetch_skimap_ids` | Collected / Prepared |
| **Overpass / OSM** | API (3 зеркала) | Объекты в радиусе 6 км (отели/кафе/развлечения/транспорт), центроид объектов катания, теги `piste:difficulty`/`piste:type` | `geocode_resorts`, `recompute_resort_data` | Collected / Prepared |
| **Skimap.org** | веб (парсинг источников) | ID и ссылка на схему трасс | `fetch_skimap_ids` | Prepared |
| **Wikipedia RU** | API | Sitelink статьи (fallback для details_url) | `fetch_skimap_ids` | Prepared |
| **Open-Meteo Archive** | API | 30-летний климат ERA5 (ноябрь–апрель): снег, температура, снежные/морозные дни | `recompute_resort_data` | Cache → Prepared/Mart |
| **Open-Meteo Forecast** | API | Прогноз на 10 дней: температура, осадки, снегопад, ветер, snow_depth | `fetch_weather_forecast` | Collected → Mart |
| **OurAirports** | CSV (GitHub) | Ближайший аэропорт: расстояние, IATA | `recompute_resort_data` | Cache |
| **Росстат / ЕМИСС** | CSV (raw) | Турпоток региона: поездки 2022–2025, ночёвки, рост | `regional_demand` | Prepared |
| **Сайты курортов** | HTML-парсеры | Цены ски-пассов (Шерегеш, Кукисвумчорр, Гора Белая) | `prices/run_parsers` + `parsers/*` | Prepared |
| **Nominatim** | API | Валидация региона при геокодинге | `geocode_resorts` | Collected (статус) |

## 3. Каскады и фолбэки

### 3.1 Координаты (`geocode_resorts.py`)
Каскад по убыванию надёжности:
1. **OpenSkiMap** — готовые координаты skiArea (`exact` / `openskimap`);
2. **Wikidata** — P625 по Q-id из поиска по имени (`wikidata`);
3. **Overpass/OSM** — центроид OSM-объектов катания вокруг ориентира заказчика (`osm_centroid`);
4. **Ориентир заказчика** (`reference`) — если ничего не нашлось.

Приоритет при выборе итоговой точки: `openskimap=5 > osm_centroid=4 > wikidata=3`. Валидация региона — через Nominatim (обратное геокодирование). Если ничего нет — статус `review`.

### 3.2 Внешние ссылки `details_url` (`fetch_skimap_ids.py`)
Каскад: **Skimap.org → Wikipedia (RU) → Wikidata → NULL**. Skimap ID извлекается из `openskimap_sources` (паттерн `skimap.org:ID`), из Wikidata P6400 или из ручной таблицы `KNOWN_SKIMAP_IDS`.

### 3.3 Цены (`prices/run_parsers.py`)
Приоритет (по убыванию):
1. **`resorts_manual.json`** — ручные цены `source_quality="manual"` (проверены, приоритет);
2. **`resorts_manual.json`** — месячная матрица `source_quality="secondary"/"official"`;
3. **живые скраперы** — `parse_sheregesh.py`, `parse_kukisvumchorr.py`, `parse_gora_belaya.py`.

Если цены нет нигде — нейтральные **50 баллов** в скоринге.

## 4. Инкрементальность, кэш и обработка таймаутов

- **Климат** — кэш `data/cache/climate_daily.json`; докачиваются только недостающие сезоны (защита от 429 и дневного лимита Open-Meteo Archive).
- **Аэропорты** — кэш `data/cache/airports.csv` (OurAirports скачивается один раз).
- **Координаты** — `KEEP_QUALITIES = {exact, osm_centroid, openskimap}`: подтверждённые качества не перегеокодируются при инкрементальном прогоне (только `--force` пересматривает всё).
- **Overpass** — 3 зеркала с фолбэком (`overpass-api.de`, `overpass.kumi.systems`, `maps.mail.ru`); у mail.ru самоподписанный сертификат — проверка SSL отключается.
- **Троттлинг** — паузы между запросами: `wikidata=0.6 с`, `overpass=2.5 с` (вежливость к публичным API).
- **USER_AGENT** — `TravelDesignerStudentWorkshop/1.0 open-data-research`.
- **rescore идемпотентен** — на неизменённых входах даёт бит-в-бит тот же результат (фиксированный seed Monte Carlo `SEED=42`).

## 5. Парсинг цен

Парсеры `src/collect/prices/parsers/`:
- `base.py` — общий `fetch` (HTTP GET) + `clean` (убрать теги/пробелы);
- `parse_sheregesh.py` — Шерегеш;
- `parse_kukisvumchorr.py` — Кукисвумчорр;
- `parse_gora_belaya.py` — Гора Белая.

Каждый парсер: `URL` + `extract()` → `{min, max}`. Если парсер не нашёл цену — `status="парсер: не нашёл цену"`, цена не записывается.

## 6. Показатели и скоринг (13 → 5 → индекс)

13 нормированных показателей (0–100) группируются в 5 компонентов; веса в сумме дают 100:

| Компонент | Показатели (веса внутри) | Вес |
|---|---|---|
| Региональный спрос | Поездки (25) + Рост (10) + Длительность (5) | **40** |
| Инфраструктура | Трассы (10) + Подъёмники (7) + Размещение (5) + Питание/досуг (3) | **25** |
| Зимние условия | Снежные дни (8) + Морозные дни (6) + Снегопад (6) | **20** |
| Доступность | Аэропорт (8) + Транспорт (2) | **10** |
| Цена | Ски-пасс (5) | **5** |

Нормализация: min-max, log-min-max (поездки/OSM/снегопад), обратная (аэропорт/цена — «меньше лучше»). Нет данных → нейтральные **50**.

Индекс: `popularity_score = Σ(балл × вес) / 100`. Уверенность `confidence_score` зависит от полноты, наличия цены и подтверждённых координат.

Пресеты (`scoring_presets.json`, 6 шт.) перевзвешивают **только 5 компонентных баллов** — 13 показателей и нормализация не меняются. Базовый пресет `base` воспроизводит `popularity_score` (контрольная точка).

## 7. Полный перечень скриптов пайплайна

| Скрипт | Читает | Пишет | Что делает |
|---|---|---|---|
| `collect/geocode_resorts.py` | resorts_manual.json + API | collected/coordinates_verified.json | Каскад координат |
| `transform/apply_coordinates.py` | resorts_manual.json + coordinates | prepared/resorts.json | Справочник курортов |
| `collect/recompute_resort_data.py` | prepared/resorts.json + OSM/Open-Meteo/OurAirports | prepared/resorts.json, mart/climate_monthly.csv, cache/* | OSM-инфра, трассы, климат, аэропорт |
| `transform/regional_demand.py` | raw/rosstat_*.csv | prepared/region_metrics.json | Нормирует турпоток |
| `collect/prices/run_parsers.py` | prices_*.json + парсеры | prepared/prices.json | Цены ски-пассов |
| `collect/fetch_skimap_ids.py` | prepared/resorts.json + API | prepared/resorts.json | Каскад ссылок |
| `transform/build_resort_features.py` | prepared/* | mart/resort_features.csv | Сырые признаки (66 кол.) |
| `scoring/score_resorts.py` | resort_features + scoring_weights.json | mart/resort_scores.csv, scoring_weights.csv | Скоринг 13→5→индекс |
| `scoring/preset_engine.py` | resort_scores + scoring_presets.json | mart/presets.csv, resort_preset_components.csv | 6 пресетов (960 строк) |
| `analytics/ranking_insights.py` | resort_scores + resort_features + presets | mart/ranking_stability.csv (192), resort_components.csv, resort_reasons.csv | Monte Carlo + локальный рейтинг + причины |
| `analytics/catalog_builder.py` | resort_preset_components + resort_features | mart/catalog_scenarios.csv, catalog_members.csv | Сценарии каталога |
| `analytics/build_atlas_catalog.py` | resort_preset_components + presets + resort_features + resort_scores + ranking_stability + scoring_weights + catalog_* | mart/atlas_catalog.csv (732×86) | Широкая витрина стр. 1 |
| `collect/fetch_weather_forecast.py` | prepared/resorts.json + Open-Meteo Forecast | collected/weather_forecast.json | Прогноз 10 дней |
| `analytics/trip_conditions.py` | collected/weather_forecast.json | mart/weather_forecast_daily.csv | Состояние трассы (эвристика) |
| `load/load_supabase.py` | mart/*.csv | Supabase (13 таблиц) | Загрузка витрин |

## 8. Режимы пайплайна

| Режим | Цепочка | Что делает |
|---|---|---|
| `full` | merge → geocode → apply → recompute → regional_demand → prices → skimap → features → score → preset → ranking → catalog → atlas + weather + load | Полная пересборка с нуля |
| `static` | merge → apply → recompute → … (без geocode) | Инкрементальный рейтинг |
| `climate` | recompute `--only-climate` → features → score → preset → ranking → catalog → atlas + load | Только 30-летний климат |
| `weather` | fetch_weather_forecast → trip_conditions → load (только weather_forecast_daily) | Только прогноз |
| `add` | merge → geocode новой точки → полная цепочка | Добавить курорт |
| `remove` | merge → apply → RATING_TAIL (без удалённого) | Удалить курорт |
| `rescore` | features → score → preset → ranking → catalog → atlas → load (все 13) | Локальный пересчёт из готовых данных |

Флаги: `--no-load` (без Supabase), `--force` (перегеокодировать/пересобрать OSM), `--only-climate`, `--quality-only`, `--piste-only` (в recompute).

## 9. Структура данных по слоям (полный список)

### RAW (`data/raw/`) — неизменяемые входы
| Файл | Что это |
|---|---|
| resorts_manual.json | Единый источник правды: курорты + цены + ссылки (правится вручную) |
| resorts.json | Эталонный справочник курортов заказчика |
| rosstat_tourist_trips.csv / nights.csv | Турпоток Росстат/ЕМИСС |

### Collected (`data/collected/`) — снимки API
- `coordinates_verified.json`, `coordinates_review.json` — координаты (каскад).
- `weather_forecast.json` — прогноз на 10 дней.

### Prepared (`data/prepared/`) — объединённые
- `resorts.json` — справочник курортов (OSM + климат + ссылки + цены).
- `region_metrics.json` — нормированный турпоток.
- `prices.json` — сводная матрица цен.

### Cache (`data/cache/`) — инкрементальные кэши
- `climate_daily.json` — 30-летний климат (докачивается инкрементально).
- `airports.csv` — OurAirports (скачивается один раз).

### Mart (`data/mart/`) — 13 витрин CSV
| Витрина | Строк | Что содержит |
|---|---|---|
| resort_features | 32 | Сырые признаки (66 кол.) |
| resort_scores | 32 | Скоринг: 13 баллов, 5 компонентов, индекс, место |
| resort_components | 160 | Компоненты (курорт × компонент) |
| resort_reasons | 71 | Объяснения «почему» |
| ranking_stability | 192 | Устойчивость + локальный рейтинг (курорт × пресет, 11 кол.) |
| presets | 6 | Словарь пресетов |
| resort_preset_components | 960 | Пресет × курорт × компонент |
| scoring_weights | 13 | Веса показателей |
| catalog_scenarios | 72 | Сценарии каталога |
| catalog_members | 630 | Состав каталога |
| atlas_catalog | 732 | Широкая витрина стр. 1 (86 кол.) |
| climate_monthly | 192 | Климат по месяцам |
| weather_forecast_daily | 320 | Прогноз (курорт × дата) |

### Reference (`data/reference/`) — справочники
- `field_dictionary.json` — словарь полей (109).
- `region_key.json` — ключ регионов.
- `scoring_weights.json` — 13 весов показателей.
- `scoring_presets.json` — 6 пресетов.

## 10. Что НЕ предполагалось исходным ТЗ (важное)

Исходное ТЗ предполагало простую схему: один скрипт `collect_resort_open_data.py` (Wikipedia/Wikidata + OSM + Open-Meteo + OurAirports в одном), `fetch_rosstat_enrichment.py`, `prepare_model_data.py` → `model_data.json` + 2 контрольных Excel.

Текущая архитектура вышла существенно дальше. Что **не предполагалось ТЗ**:

1. **Многослойная архитектура** RAW → Collected → Prepared → Mart + Cache + Reference (в ТЗ — проще: raw/collected/processed).
2. **Разбиение сбора на специализированные скрипты** (geocode, recompute, skimap, regional_demand, run_parsers, weather) вместо одного «собери всё».
3. **Мультипресетный скоринг** — 6 пресетов (base/balance/infra/snow/access/price) вместо единственных базовых весов 40/25/20/10/5.
4. **Monte Carlo устойчивость** — `ranking_stability` (5000 прогонов, seed 42, шум ×U(0.6,1.4), мультипресетно) — анализа устойчивости в ТЗ не было.
5. **Сценарии стартового каталога** — top/diversity/diversity_verified для N=5/8/10/12 с KPI сравнения.
6. **Широкая витрина `atlas_catalog`** (732×86) — материализация SQL-вьюх в Python для страницы 1.
7. **SQL-view** — `atlas_summary`, `v_index_breakdown`, `v_ranking_stability`, `v_weather_forecast` — BI-слой поверх таблиц.
8. **Supabase + Preset Cloud** (вместо Excel) + `load_supabase.py` с авто-выводом типов и PK/FK.
9. **Инкрементальный кэш** — `climate_daily.json`, `airports.csv`, `KEEP_QUALITIES` для координат.
10. **Конфиги весов** — `scoring_weights.json`, `scoring_presets.json` (веса вынесены в JSON, не хардкод).
11. **Прогноз погоды + эвристика состояния трассы** («пухляк/накат/каша/лёд/без снега») — в ТЗ был только климат.
12. **Каскад внешних ссылок** (Skimap → Wikipedia → Wikidata) и **парсеры цен** (3 сайта).
13. **Словарь полей** `field_dictionary.json` (109 полей) и **109 авто-тестов**.
14. **Округление на финальном шаге** упаковки витрин (1/2/0/3 знака) — как отдельный слой.

Итог: проект превратился из «сбора + рейтинга» в **полноценный воспроизводимый BI-конвейер**: сбор → нормализация → скоринг → пресеты → устойчивость → каталог → витрина → БД → дашборд.
