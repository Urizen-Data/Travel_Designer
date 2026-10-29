# Travel Designer (SKI ATLAS)

> Техническая «библия» проекта: архитектура данных, пайплайн, источники, витрины, методика и структура BI-дашборда.
> Единый источник правды по проекту — документация для аналитиков, разработчиков и дашборда.

---

## 1. О проекте и продуктовые границы

**Цель:** рейтинг горнолыжных курортов России + данные для дашборда Travel Designer (платформа-конструктор поездок «ски-атлас»).

**Главный вопрос проекта:** какие горнолыжные курорты первыми включить в каталог Travel Designer и почему?

**Цепочка сторителлинга (User Journey):**
Дашборд должен провести пользователя по цепочке:
1. **Где** находятся курорты (Карта).
2. **Кто** лидирует в базовой модели (Рейтинг).
3. **За счёт чего** формируется результат (Вклады компонентов).
4. **Насколько** результат устойчив (Монте-Карло).
5. **Чем** отличаются выбранные варианты (Сравнение).
6. **Что** известно о сезоне и ближайших условиях (Климат и прогноз).
7. **Какой** стартовый каталог выбрать (Сценарии).

**Что проект НЕ обещает:**
- Фактическую посещаемость каждого курорта (в открытом доступе её нет).
- Универсальный ответ «где лучше кататься» для любого человека.
- Состояние открытых трасс и подъёмников в реальном времени.
- Полный бюджет поездки, время трансфера по дороге и лавинную безопасность.
- Персональную рекомендацию по уровню катания без специальных данных.

**Ключевые числа:**
- **32 курорта** в **20 регионах** России (список задан заказчиком — «Приложение В» ТЗ);
- **5 компонентов**, **13 нормированных показателей**;
- **13 витрин-датасетов** (CSV) в `data/mart/`, загружаемых в Supabase;
- **66 колонок** в `resort_features.csv` (сырые факты), **27 колонок** в `resort_scores.csv` (скоринг);
- **109 полей** в словаре `data/reference/field_dictionary.json`;
- **107 авто-тестов**.

**Происхождение данных.** Seed (`resort_seed.csv`: название + регион + нас.пункт + опц. координаты) и ориентиры координат задал заказчик. Всё остальное собирается скриптами из открытых источников: OpenSkiMap, Overpass/OSM, Wikidata, Skimap.org, Open-Meteo, OurAirports, Росстат/ЕМИСС.

---

## 2. Архитектура данных (слои)

Данные текут по слоям **RAW → Collected → Prepared → Mart**, плюс **Cache** (инкрементальные кэши) и **Reference** (справочники).

### Слои данных и ответственные скрипты

| Слой | Папка | Кто создаёт |
|---|---|---|
| **RAW** (неизменяемые входы) | `data/raw/` | Вручную / заказчик |
| **Collected** (сбор) | `data/collected/` | `geocode_resorts.py`, `apply_coordinates.py`, `fetch_weather_forecast.py` |
| **Prepared** (объединённые) | `data/prepared/` | `apply_coordinates.py`, `regional_demand.py`, `run_parsers.py`, `recompute_resort_data.py`, `fetch_skimap_ids.py` |
| **Mart** (витрины CSV) | `data/mart/` | `build_resort_features.py`, `score_resorts.py`, `preset_engine.py`, `ranking_insights.py`, `catalog_builder.py`, `build_atlas_catalog.py`, `trip_conditions.py`, `recompute_resort_data.py` |
| **Cache** (инкрементальные кэши) | `data/cache/` | `recompute_resort_data.py` |
| **Reference** (справочники) | `data/reference/` | `regions.py`, вручную |

**Состав файлов по слоям:**
*   **RAW:** `resort_seed.csv`, `resorts.json` (эталон заказчика), `resorts_manual.json` (ручные курорты), `prices_monthly.json`, `prices_manual.json` (ручные цены), `rosstat_tourist_trips.csv`, `rosstat_tourist_nights.csv`.
*   **Collected:** `coordinates_verified.json`, `coordinates_review.json`, `weather_forecast.json`.
*   **Prepared:** `resorts.json` (справочник курортов), `region_metrics.json`, `prices.json`.
*   **Mart:** 13 датасетов (9 базовых + `presets` + `resort_preset_components` + `scoring_weights` + `atlas_catalog`).
*   **Cache:** `climate_daily.json`, `airports.csv`.
*   **Reference:** `field_dictionary.json`, `region_key.json`, `scoring_weights.json`, `scoring_presets.json`.

### Диаграмма потока данных (Data Flow)

```mermaid
flowchart TD
    %% 1. Сырые данные
    subgraph L1 ["1. RAW (Сырые данные)"]
        direction LR
        SEED["resort_seed.csv"]
        RESORTS_MAN["resorts_manual.json"]
        ROSSTAT["Росстат"]
        PRICES_RAW["prices_monthly.json"]
        PRICES_MAN["prices_manual.json"]
    end

    %% 2. Подготовка
    subgraph L2 ["2. Prepared (Объединение)"]
        direction LR
        COORDS["Координаты"]
        RESORTS["resorts.json<br/>(OSM + Климат)"]
        REGIONS["region_metrics.json"]
        PRICES["prices.json"]
    end

    %% Кэши
    subgraph CACHE ["Cache"]
        direction LR
        CLIMC["climate_daily.json"]
        AIR["airports.csv"]
    end

    %% 3. Факты
    subgraph L3 ["3. Mart (Факты)"]
        direction LR
        RF["resort_features.csv"]
        CLIM["climate_monthly.csv"]
        FORECAST["weather_forecast.json"]
    end

    %% 4. Аналитика
    subgraph L4 ["4. Mart (Аналитика)"]
        direction LR
        RS["resort_scores.csv"]
        PRESPRE["presets.csv<br/>resort_preset_components.csv"]
        INSIGHTS["ranking_stability (192),<br/>components, reasons"]
        CATALOG["catalog_scenarios,<br/>members"]
        ATLAS["atlas_catalog.csv<br/>(732 × 86)"]
        WFD["weather_forecast_daily.csv"]
    end

    %% 5. Загрузка
    DB[(Supabase)]

    %% Связи (Слой 1 -> Слой 2)
    SEED -->|geocode| COORDS
    SEED -->|apply| RESORTS
    COORDS -->|apply| RESORTS
    
    ROSSTAT -->|regional_demand| REGIONS
    PRICES_RAW -->|run_parsers| PRICES
    RESORTS_MAN -->|merge_resorts| SEED
    PRICES_MAN -->|run_parsers| PRICES

    %% Кэши
    RESORTS <-->|recompute| CLIMC
    AIR -->|справочник| RESORTS

    %% Слой 2 -> Слой 3
    RESORTS -->|build| RF
    REGIONS -->|build| RF
    PRICES -->|build| RF
    
    RESORTS -->|climate| CLIM
    RESORTS -->|forecast| FORECAST

    %% Слой 3 -> Слой 4
    RF -->|score| RS
    RS -->|preset_engine| PRESPRE
    RF -->|insights| INSIGHTS
    RS -->|catalog| CATALOG
    FORECAST -->|trip_conditions| WFD
    PRESPRE -->|build_atlas| ATLAS
    INSIGHTS -->|build_atlas| ATLAS
    CATALOG -->|build_atlas| ATLAS

    %% Загрузка в БД
    RF -->|load| DB
    RS -->|load| DB
    CLIM -->|load| DB
    WFD -->|load| DB
    INSIGHTS -->|load| DB
    CATALOG -->|load| DB
    PRESPRE -->|load| DB
    ATLAS -->|load| DB
```

---

## 3. Пайплайн и режимы (`run_pipeline.py`)

Оркестратор собирает шаги в правильном порядке и останавливается на первой ошибке.

### Состав цепочек

| Цепочка | Шаги |
|---|---|
| `RATING_FULL` | merge_resorts → geocode → apply → recompute → regional_demand → prices → skimap_ids → build_features → score → preset_engine → ranking_insights → catalog → atlas_catalog |
| `RATING_STATIC` | merge_resorts → apply → recompute → regional_demand → prices → skimap_ids → build_features → score → preset_engine → ranking_insights → catalog → atlas_catalog |
| `RATING_ADD` | как `RATING_FULL` (геокодинг новой точки + полный пересбор) |
| `WEATHER` | fetch_weather_forecast → trip_conditions |
| `CLIMATE` | recompute `--only-climate` → build_features → score → preset_engine → ranking_insights → catalog → atlas_catalog |
| `REMOVE` | merge_resorts → apply_coordinates + `RATING_TAIL` (пересборка без удалённого курорта) |
| `RATING_RESCORE` | build_features → score → preset_engine → ranking_insights → catalog → atlas_catalog → load_supabase (локально, без сетевых запросов) |
| `LOAD` | load_supabase |

### Схема режимов пайплайна

```mermaid
flowchart TD
    %% Точки входа (Режимы)
    M_FULL([--mode full])
    M_STATIC([--mode static])
    M_CLIMATE([--mode climate])
    M_ADD([--mode add])
    M_REMOVE([--mode remove])
    M_WEATHER([--mode weather])
    M_RESCORE([--mode rescore])

    %% Ветка рейтинга
    subgraph Rating ["Цепочка рейтинга (RATING)"]
        direction TB
        MG[merge_resorts]
        G[geocode_resorts] --> A[apply_coordinates]
        MG --> G
        MG --> A
        A --> R[recompute_resort_data]
        R --> D[regional_demand]
        D --> P[prices/run_parsers]
        P --> S[fetch_skimap_ids]
        S --> B[build_resort_features]
        B --> SC[score_resorts]
        SC --> PE[preset_engine]
        SC --> RI[ranking_insights]
        PE --> RI
        RI --> CB[catalog_builder]
        CB --> AC[build_atlas_catalog]
    end

    %% Ветка погоды
    subgraph Weather ["Цепочка погоды (WEATHER)"]
        direction TB
        F[fetch_weather_forecast] --> TC[trip_conditions]
    end

    %% Загрузка
    DB[(load_supabase)]

    %% Подключение режимов к началу цепочек
    M_FULL --> MG
    M_FULL --> F

    M_STATIC --> MG

    M_CLIMATE -.->|"только климат"| R

    M_ADD -.->|"новый курорт"| MG
    M_REMOVE -.->|"удаление"| MG

    M_WEATHER --> F
    M_RESCORE -.->|"локально, без сети"| B

    %% Завершение цепочек загрузкой
    CB --> DB
    AC --> DB
    PE --> DB
    TC --> DB
```

### Флаги `run_pipeline.py`

| Флаг | Для чего |
|---|---|
| `--mode` | `{full, static, climate, weather, add, remove, rescore}` — обязательный выбор режима |
| `--force` | перегеокодировать координаты и пересобрать OSM заново (игнорировать инкрементальность) |
| `--no-load` | не загружать в Supabase (только локальные файлы) |
| `--skip-overpass-check` | не проверять доступность Overpass перед прогоном |
| `--name`, `--region`, `--settlement` | не-интерактивный ввод для `add`/`remove` |

**Флаги `recompute_resort_data.py`** (вызываются внутри цепочек):
*   `--only-climate`: только 30-летний климат (пропуск OpenSkiMap/OSM/аэропортов).
*   `--quality-only`: только производные поля качества.
*   `--piste-only`: только сложность/типы трасс.
*   `--force`: пересобрать статику заново.

### Ручное добавление курортов и цен (JSON-конфиги)

Вместо CLI (`--mode add`) и правки CSV можно управлять сущностями простыми JSON-файлами в `data/raw/`:

**`resorts_manual.json`** — ручные курорты (дополняют `resort_seed.csv`, не заменяют его):
```json
{"resorts": [
  {"name_ru": "Новый Курорт", "region": "Республика Алтай",
   "settlement": "с. Телецкое", "lat": 51.7, "lon": 87.5}
]}
```
*   `name_ru` и `region` обязательны; `settlement`, `lat`, `lon` — опциональны.
*   Если указаны и `lat`, и `lon` — используются как точные координаты; иначе работает геокодинг (`geocode_resorts`).
*   При запуске любой ветки «рейтинг» (`full`/`static`/`add`/`remove`) шаг `merge_resorts` дописывает новые курорты в `resort_seed.csv` (без дублей по `name_ru`), после чего `apply_coordinates` пересобирает `resorts.json`.

**`prices_manual.json`** — ручные цены (приоритет над `prices_monthly.json` и парсерами):
```json
{"prices": [
  {"resort_name": "Новый Курорт", "adult_price_min_rub": 3000,
   "adult_price_max_rub": 4500, "month": null,
   "tariff_product": "Ски-пасс на 1 день", "source_quality": "manual"}
]}
```
*   Привязка к курорту — по `resort_name` (`name_ru`) или явному `resort_id`.
*   Приоритет цен: `prices_manual.json` > `prices_monthly.json` > парсеры; если цены нет нигде — нейтральные 50 баллов в скоринге.
*   Ручные цены перекрывают месячную матрицу и парсеры и корректно вливаются в `prepared/prices.json`.

**Итоговый сценарий:** вписываете курорт + цену в оба JSON → `python run_pipeline.py --mode static` → в дашборде появляется новый курорт с указанной ценой.

---

## 4. Сущности и контракт гранулярности (Для BI)

Это главный технический договор для Superset. Смешивание гранулярностей в одной широкой таблице без контроля кардинальности **запрещено**.

| Сущность (Датасет) | Одна строка означает | Уникальный ключ |
|---|---|---|
| `resort_features` | один курорт и его факты | `resort_id` |
| `resort_scores` | один курорт и его баллы | `resort_id` |
| `resort_components` | компонент курорта | `resort_id + component` |
| `ranking_stability` | устойчивость курорта в пресете | `resort_id + preset_id` |
| `resort_reasons` | одно объяснение курорта | `resort_id + reason_code` |
| `climate_monthly` | один месяц курорта | `resort_id + month` |
| `weather_forecast_daily` | одна дата прогноза курорта | `resort_id + date` |
| `catalog_scenarios` | один готовый сценарий | `scenario_id` |
| `catalog_members` | курорт внутри сценария | `scenario_id + resort_id` |
| `presets` | один пресет (словарь весов) | `preset_id` |
| `resort_preset_components` | компонент курорта в пресете | `preset_id + resort_id + component` |
| `atlas_catalog` | курорт в сценарии (широкая витрина стр. 1) | `scenario_id + resort_id + preset_id` |
| `scoring_weights` | один показатель модели (вес) | `indicator` |

**Правило:** Нельзя напрямую джойнить `climate_monthly` и `weather_forecast_daily` по одному `resort_id` — получится декартово произведение (размножение строк). Для Superset используются отдельные датасеты.

---

## 5. Источники данных и фичи

### 5.1. Координаты — `geocode_resorts.py`
Каскад: OpenSkiMap (`exact`) → Wikidata (`wikidata`) → Overpass (`osm_centroid`) → Ориентир заказчика (`reference`). Если ничего нет — `review`. Валидация региона через Nominatim.

### 5.2. Инфраструктура — OpenSkiMap + Overpass
- **OpenSkiMap** — основной источник: сложность, длина, высоты (`piste_min/max_elevation_m`), подъемники.
- **Overpass** — fallback для сложности (если нет в OpenSkiMap) и **всегда** для amenities (отели, кафе в радиусе 6 км).

### 5.3. Ссылки (`details_url`) — `fetch_skimap_ids.py`
Каскад: Skimap.org → Wikipedia (RU) → Wikidata → NULL.

### 5.4. Климат (статика, 30 лет)
- **Источник:** Open-Meteo Historical API (модель ERA5).
- **Период:** 30 зимних сезонов (ноябрь–апрель).
- **Параметр `elevation`:** Передается средняя высота склона `(piste_min + piste_max) / 2`. Open-Meteo применяет температурный градиент, чтобы данные отражали реальную высоту катания, а не подножие.
- **Кэш:** `data/cache/climate_daily.json`. Докачивает только недостающие сезоны (защита от 429).

### 5.5. Прогноз (динамика, 10 дней)
- **Источник:** Open-Meteo Forecast API.
- **Горизонт:** 10 дней (баланс точности и полезности).
- **Правило:** `trip_conditions.py` определяет предпосылки состояния трассы («пухляк», «накат», «каша», «лёд», «без снега») на основе осадков, температуры и ветра.

---

## 6. Методика скоринга (`score_resorts.py`)

13 показателей группируются в 5 компонентов. Веса в сумме дают 100.

| Компонент | Показатели | Вес |
|---|---|---|
| Региональный спрос | Поездки (25) + Рост (10) + Длительность (5) | **40** |
| Инфраструктура | Трассы (10) + Подъемники (7) + Размещение (5) + Инфраструктура (3) | **25** |
| Зимние условия | Снежные дни (8) + Морозные дни (6) + Снегопад (6) | **20** |
| Доступность | Аэропорт (8) + Транспорт (2) | **10** |
| Цена | Стоимость ски-пасса (5) | **5** |

Веса (и русские подписи) задаются в `data/reference/scoring_weights.json` и автоматически выгружаются в витрину `scoring_weights` (13 строк: показатель → компонент → вес), которая загружается в Supabase и доступна на дашборде. Изменили вес в конфиге → повторный прогон → дашборд показывает новые значения.

**Формулы:**
- **Min-max:** `100·(x−min)/(max−min)`
- **Log min-max:** Для поездок, OSM-объектов и снегопада (сглаживает выбросы).
- **Обратная:** `100 − log_min_max` для аэропорта и цены (чем меньше, тем лучше).
- **None (нет данных):** Дает нейтральные **50 баллов**.

**Индекс:** `popularity_score = Σ(балл × вес) / 100`.
**Уверенность:** `confidence_score` зависит от полноты данных (completeness), наличия цены и подтвержденных координат.

### Пресеты скоринга (сценарии приоритетов)

Веса вынесены в два конфига `data/reference/`:
- `scoring_weights.json` — 13 весов показателей + 5 весов компонентов (читает и валидирует `score_resorts.py`);
- `scoring_presets.json` — 6 пресетов (id + название + описание + 5 весов компонентов).

Движок `src/scoring/preset_engine.py` перевзвешивает **только 5 компонентных баллов** (не трогая 13 показателей и нормализацию):

```text
scenario_score = Σ component_score × component_weight_pct / 100
```

| Пресет | Спрос | Инфра | Зима | Доступ | Цена |
|---|--:|--:|--:|--:|--:|
| base — Базовый каталог | 40 | 25 | 20 | 10 | 5 |
| balance — Баланс для катания | 5 | 35 | 35 | 20 | 5 |
| infra — Инфраструктура важнее | 5 | 60 | 20 | 10 | 5 |
| snow — Снег важнее | 5 | 20 | 60 | 10 | 5 |
| access — Доступность важнее | 5 | 25 | 20 | 45 | 5 |
| price — Цена важнее | 5 | 20 | 20 | 15 | 40 |

Результат — две витрины: `presets.csv` (словарь) и `resort_preset_components.csv` (long: пресет × курорт × компонент = 960 строк). Базовый пресет `base` воспроизводит `popularity_score` (контрольная точка).

**Устойчивость и локальный рейтинг — тоже мультипресетные** (`ranking_insights.py`): `ranking_stability.csv` — **192 строки (32 курорта × 6 пресетов) × 11 колонок** (`resort_id, preset_id, preset_name_ru, name_ru, region, median_rank, rank_p5, rank_p95, top10_frequency, local_score, local_rank`). Для каждого пресета — Монте-Карло (5000 прогонов, seed 42, мультипликативный шум ×U(0.6, 1.4) вокруг весов ЭТОГО пресета, перенормировка к 100) → `median_rank`/`rank_p5`/`rank_p95`/`top10_frequency`; `local_score` = взвешенная сумма 4 нерегиональных компонентов (infra, winter, access, price) с весами пресета, перенормированная к 100% (regional не участвует); `local_rank` = место по `local_score` внутри пресета.

**Итоговая витрина страницы 1 — `atlas_catalog.csv`** (`build_atlas_catalog.py`): **732 строки × 86 колонок** = `all_top` (полный рейтинг, 192) + `all_diversity` (лучший курорт региона, ~120) + member-сценарии `top`/`diversity` (~420). Из `ranking_stability` в неё идут только `stability_median_rank` (переименованный `median_rank`), `local_score`, `local_rank` (мерж по `resort_id + preset_id`); `rank_p5`/`rank_p95`/`top10_frequency` остаются только в `ranking_stability` (стр. «Устойчивость рейтинга»).

---

## 7. Архитектура дашборда в Superset

### Пресеты скоринга (выбор приоритета)
Реализовано фиксированными пресетами (не SQL/Jinja): `preset_engine.py` считает `resort_preset_components.csv`, а `ranking_insights.py` — `ranking_stability.csv` (192 строки: курорт × пресет). На дашборде — селектор `preset_id` (Native Filter), который перестраивает рейтинг/карту/вклады/устойчивость/локальный рейтинг. Страница 1 работает на единой витрине `atlas_catalog` (см. ниже).

### Страница 1. Атлас и рейтинг (Главная)
**Вопрос:** Где находятся курорты и кто лидирует?
- Карта 32 объектов (цвет = рейтинг, tooltip = ссылки и факты).
- Базовый рейтинг (горизонтальные полосы с 5 вкладами).
- KPI покрытия данных.
- Таблица базового и сценарного места.
- Блок качества и предупреждений.

**Датасет:** единая витрина `atlas_catalog` (732 строки × 86 колонок) — `all_top` (полный рейтинг по 6 пресетам), `all_diversity` (лучший курорт региона), member-сценарии `top`/`diversity`.

### Страница 2. Сравнение курортов
**Вопрос:** Чем отличаются выбранные 1–4 курорта?
- 5 компонентных баллов (график или таблица).
- Матрица фактов (длина трасс, сложность, высоты).
- Цены с периодами.
- Причины и компромиссы.
- Парное `ΔS(A−B)` для выбранных курортов.

### Страница 3. Сезон и погода
**Вопрос:** Когда и при каких условиях рассматривать поездку?
- Исторический профиль (климат по месяцам).
- Прогноз на 10 дней (матрица курорт × дата).
- Деталь выбранного курорта (температура, ветер, снегопад).
- Причины, ограничения и время получения данных. Климат и прогноз не смешиваются.

### Страница 4. Стартовый каталог
**Вопрос:** Какой набор курортов включить первым?
- N = 5, 8, 10, 12. Стратегии: top, diversity, diversity_verified.
- KPI: средний индекс, число регионов, концентрация.
- Карта и таблица состава.
- Сравнение с простым top-N.

---

## 8. UX-правила и объяснимость в UI

Для каждой цифры в дашборде пользователь должен понимать, что это:
1. **Факт:** «расстояние до аэропорта по прямой — 35 км».
2. **Модельная оценка:** «высокий балл доступности по текущей нормализации».
3. **Ограничение:** «время трансфера по дороге не рассчитано».

**Запрещено использовать как готовые выводы:**
- «Лучший курорт» без уточнения критерия.
- «Подходит новичкам» по одной доле easy-сегментов.
- «Дешевле поездка» по одному ски-пассу.
- «Открыто» по прогнозу погоды.
- «Лёд» или «пухляк» как подтвержденное состояние трассы (только «предпосылки»).
- «Полная инфраструктура» по OSM-счетчикам.

---

## 9. Запуск и Troubleshooting

```powershell
python run_pipeline.py --mode full      # Полная пересборка
python run_pipeline.py --mode static    # Инкрементальный рейтинг
python run_pipeline.py --mode climate   # Только 30-летний климат
python run_pipeline.py --mode weather   # Только 10-дневный прогноз
python run_pipeline.py --mode add       # Добавить курорт
python run_pipeline.py --mode remove    # Удалить курорт
python run_pipeline.py --mode rescore            # пересчёт + загрузка в Supabase
python run_pipeline.py --mode rescore --no-load  # пересчёт без загрузки (для тестов)
```

**Troubleshooting Superset:**
При ошибке `SSL SYSCALL error` или `connection already closed` (Supabase закрывает спящие соединения), в настройках подключения (Advanced -> Other -> Engine Parameters) добавить:
`{"poolclass": "sqlalchemy.pool.NullPool", "pool_pre_ping": true}`.

**Требования:** Python 3.10+. Секреты Supabase и токены Mapbox хранятся строго в `.env` и не коммитятся в Git.

**Загрузка в Supabase (`load_supabase.py`):** пайплайн владеет только таблицами из `data/mart/*.csv` — колонки и ключи читаются из CSV (не хардкодятся). При неизменной схеме таблицы обновляются на месте (`CREATE TABLE IF NOT EXISTS` → очистка → вставка); при изменении схемы — пересоздаются (`DROP` + `CREATE`). VIEW (`atlas_summary`, `v_index_breakdown`, `v_weather_forecast`) создаются аналитиком в SQL Lab и пайплайном не трогаются. **Если на пересоздаваемую таблицу ссылаются VIEW — их нужно вручную дропнуть до загрузки и пересоздать после** (DDL вьюх держим в `data/reference/views_backup.sql`).

**Выборочная загрузка:** `load_supabase.py <таблицы...>` грузит только перечисленные таблицы (без аргументов — все). Режим `weather` грузит только `weather_forecast_daily` (погода ни от чего не зависит по FK). Остальные режимы грузят все 13: таблицы скоринга связаны внешними ключами с `climate_monthly`/`weather_forecast_daily` (через `resort_scores`), поэтому выборочная загрузка там сломала бы `DELETE`.

---

## 10. Ограничения и допущения

- **Индекс потенциала ≠ популярность**: оценка по открытым данным, а не фактическая посещаемость.
- **Региональный спрос** относится ко всему субъекту РФ, а не к конкретному курорту.
- **OSM/Overpass** отражает полноту картирования; сегменты трасс ≠ реальные трассы; соседние курорты могут пересекаться по радиусам 6 км.
- **Климат ERA5** — модельный (~25 км) и приведён к средней высоте склона (`elevation`); не заменяет метеостанцию на склоне.
- **Min-max нормализация** зависит от состава выборки: добавление/удаление курорта меняет баллы всех.
- **Геокодинг** «название + регион + settlement» надёжен для большинства, но неоднозначные названия уходят в `review`.
- **Цены** собраны не для всех курортов; без цены — нейтральные 50.
- **Лимит Open-Meteo Archive** — дневной: полный 30-летний сбор может потребовать нескольких запусков (инкрементальный кэш `climate_daily.json` это поддерживает).
- **rescore НЕ видит новых данных**: если появились новые курорты, цены, климат или ссылки — нужен `--mode static` или `--mode full`.
- **rescore идемпотентен**: на неизменённых входах даёт бит-в-бит тот же результат.
- **rescore всегда загружает результат в Supabase**; `--no-load` — только для тестов и CI.