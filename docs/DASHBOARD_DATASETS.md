# Справочник датасетов дашборда

Все витрины дашборда собраны в `data/mart/` в формате CSV. Полный словарь
полей — в `data/reference/field_dictionary.json` (109 полей).
Ключи-идентификаторы (`resort_id`, `name_ru`, `region`, `scenario_id`) не
описываются — это справочные поля.

## Сводка

| Файл | Назначение | Строк | Полей |
|---|---|---|---|
| `resort_scores.csv` | Результаты скоринга: 13 баллов, 5 компонентов, индекс, место, качество | 32 | 27 |
| `resort_features.csv` | Сырые признаки из источников (координаты, OSM, климат, спрос, цены, ссылки) | 32 | 66 |
| `resort_components.csv` | Компоненты рейтинга (курорт × компонент) | 160 | 8 |
| `ranking_stability.csv` | Устойчивость и локальный рейтинг (курорт × пресет) | 192 | 11 |
| `resort_reasons.csv` | Объяснения «почему» (длинный формат: причина × строка) | 89 | 5 |
| `catalog_scenarios.csv` | Сценарии каталога и их KPI (6 пресетов × 3 стратегии × 4 N) | 72 | 16 |
| `catalog_members.csv` | Состав каталога по сценариям | 630 | 10 |
| `climate_monthly.csv` | Месячный климат ноябрь–апрель | 192 | 12 |
| `weather_forecast_daily.csv` | Прогноз 7 дней (курорт × дата) | 224 | 19 |
| `atlas_catalog.csv` | Единая витрина страницы 1 (широкий рейтинг + сценарии) | 732 | 86 |

## Поля по датасетам

### resort_scores.csv

Результаты скоринга: 13 баллов, 5 компонентов, индекс, место, качество. 32 строк, 27 полей.

- `resort_id` — справочное поле/ключ
- `name_ru` — справочное поле/ключ
- `region` — справочное поле/ключ
- `latitude` — справочное поле/ключ
- `longitude` — справочное поле/ключ
- `region_trips_score` — Поездки (балл) (баллы 0–100) — Нормировка trips_2025 (log min-max)
- `region_growth_score` — Рост поездок (балл) (баллы 0–100) — clip(50 + 200·рост, 0, 100)
- `avg_stay_score` — Длительность (балл) (баллы 0–100) — clip((ночей−1)/6·100, 0, 100)
- `pistes_score` — Трассы (балл) (баллы 0–100) — Нормировка piste_segments_6km
- `lifts_score` — Подъёмники (балл) (баллы 0–100)
- `lodging_score` — Размещение (балл) (баллы 0–100)
- `amenities_score` — Питание и досуг (балл) (баллы 0–100)
- `snow_days_score` — Снежные дни (балл) (баллы 0–100)
- `freezing_days_score` — Морозные дни (балл) (баллы 0–100)
- `snowfall_score` — Снегопад (балл) (баллы 0–100)
- `airport_score` — Аэропорт (балл) (баллы 0–100) — Обратная нормировка расстояния (меньше = лучше)
- `transport_score` — Транспорт (балл) (баллы 0–100)
- `price_score` — Цена (баллы 0–100) — Только для курортов с наблюдаемой ценой; без цены — нейтрально 50
- `regional_score` — Региональный спрос (баллы 0–100) — Турпоток всего субъекта РФ, не конкретного курорта
- `infrastructure_score` — Инфраструктура (баллы 0–100) — OSM-объекты в радиусе 6 км; полнота зависит от картирования
- `winter_score` — Зимние условия (баллы 0–100) — Климатические средние за сезоны, не прогноз
- `accessibility_score` — Доступность (баллы 0–100) — Расстояние до аэропорта по прямой, не трансфер
- `popularity_score` — Индекс потенциала (баллы 0–100) — Не фактическая популярность, а расчётный потенциал по доступным данным
- `confidence_score` — Оценка полноты данных (баллы 0–100) — Служебный балл полноты, не вероятность и не качество курорта
- `details_url` — Ссылка на подробную информацию (—) — Ссылка на подробную информацию о курорте (Skimap/Wikipedia/Wikidata)
- `details_url_source` — Источник ссылки (—) — Skimap / Wikipedia / Wikidata
- `rank` — Место в рейтинге (место)

### resort_features.csv

Сырые признаки из источников (координаты, OSM/OpenSkiMap, климат, спрос, цены, ссылки). 32 строк, 66 полей.

- `resort_id` — справочное поле/ключ
- `name_ru` — справочное поле/ключ
- `region` — справочное поле/ключ
- `latitude` — справочное поле/ключ
- `longitude` — справочное поле/ключ
- `coordinate_quality_new` — справочное поле/ключ
- `coordinate_status` — Статус координат (—) — updated / warn / needs_review
- `piste_segments_6km` — OSM-сегменты трасс, 6 км (шт.) — Сегменты не равны реальным трассам; зависит от полноты картирования
- `lift_lines_6km` — OSM-линии подъёмников, 6 км (шт.)
- `lodging_objects_6km` — Объекты размещения, 6 км (шт.) — Количество объектов не равно вместимости
- `food_objects_6km` — Питание, 6 км (шт.)
- `attraction_objects_6km` — Достопримечательности, 6 км (шт.)
- `transport_objects_6km` — Транспортные объекты, 6 км (шт.)
- `piste_ways_total` — Piste-сегментов всего (OSM) (шт.) — Все типы трасс в радиусе 6 км
- `piste_length_km` — Длина трасс (км) — Суммарная длина downhill-трасс (OpenSkiMap/OSM)
- `piste_difficulty_novice` — Трассы: novice (новичок) (шт.) — downhill с piste:difficulty=novice
- `piste_difficulty_easy` — Трассы: easy (лёгкие) (шт.)
- `piste_difficulty_intermediate` — Трассы: intermediate (средние) (шт.)
- `piste_difficulty_advanced` — Трассы: advanced (сложные) (шт.)
- `piste_difficulty_expert` — Трассы: expert (шт.)
- `piste_difficulty_freeride` — Трассы: freeride (шт.)
- `piste_difficulty_unknown` — Трассы без тега сложности (шт.) — downhill-сегменты без piste:difficulty
- `piste_type_nordic` — Беговые трассы (nordic) (шт.)
- `piste_type_snow_park` — Сноу-парки (snow_park) (шт.)
- `piste_type_other` — Прочие типы трасс (шт.)
- `piste_difficulty_coverage` — Покрытие тегов сложности (доля 0–1) — Доля downhill-сегментов с piste:difficulty
- `piste_min_elevation_m` — Мин. высота трасс (м)
- `piste_max_elevation_m` — Макс. высота трасс (м)
- `avg_snowfall_cm_per_season` — Снегопад за сезон (см)
- `avg_freezing_days_per_season` — Морозные дни за сезон (дней)
- `avg_snow_days_per_season` — Снежные дни за сезон (дней) — Среднее по климатическим сезонам
- `max_daily_snowfall_cm` — справочное поле/ключ
- `winter_mean_temperature_c` — справочное поле/ключ
- `open_meteo_elevation_m` — справочное поле/ключ
- `nearest_airport_distance_km` — До ближайшего аэропорта (км) — По прямой; не время и не стоимость трансфера
- `nearest_airport_iata` — Код аэропорта (IATA)
- `completeness_pct` — Полнота данных (доля 0–1) — Доля заполненных обязательных полей
- `quality_flags` — Флаги качества (—) — Предупреждения о качестве данных и пересечениях OSM-радиусов
- `osm_overlap_warning` — справочное поле/ключ
- `openskimap_id` — OpenSkiMap ID (—) — ID skiArea в OpenSkiMap
- `openskimap_name` — Название в OpenSkiMap (—) — Как курорт называется в OpenSkiMap
- `official_website_url` — Официальный сайт (—) — Официальный сайт курорта
- `openskimap_sources` — Источники (OpenSkiMap) (—) — Связанные ID источников (OSM/skimap.org)
- `skimap_id` — Skimap ID (—) — Уникальный ID курорта на Skimap.org
- `skimap_url` — Ссылка на Skimap.org (—) — Ссылка на детальную карту курорта на Skimap.org
- `details_url` — Ссылка на подробную информацию (—) — Ссылка на подробную информацию о курорте (Skimap/Wikipedia/Wikidata)
- `details_url_source` — Источник ссылки (—) — Skimap / Wikipedia / Wikidata
- `trips_2022` — справочное поле/ключ
- `trips_2023` — справочное поле/ключ
- `trips_2024` — справочное поле/ключ
- `trips_2025` — Туристские поездки, 2025 (поездок) — По всему субъекту РФ (ЕМИСС/Росстат)
- `nights_2023` — справочное поле/ключ
- `nights_2024` — справочное поле/ключ
- `nights_2025` — справочное поле/ключ
- `trips_growth_2025` — Рост поездок, 2025 к 2024 (доля)
- `avg_stay_nights_2025` — Средняя длительность, 2025 (ночей на поездку)
- `coordinate_validation_status` — Статус валидации координат (—) — confirmed / provisional / needs_review; подтверждённой считается только confirmed
- `adult_skipass_avg_rub` — Ски-пасс, взрослый, 1 день (руб.) — 12 курортов (9 мануальных + 3 скрапера); продукт и период могут различаться
- `price_months_count` — Месяцев с ценой (шт.)
- `price_months_min` — Месяцы с ценой (от) (YYYY-MM)
- `price_months_max` — Месяцы с ценой (до) (YYYY-MM)
- `price_season` — Сезон цены (—) — Зимний сезон, к которому относится цена
- `price_product` — Тарифный продукт (—) — Например, «Ски-пасс на 1 день»; продукты могут различаться
- `price_source_quality` — Качество источника цены (—) — official / secondary / scraper
- `price_source_url` — Источник цены (—) — URL источника
- `price_checked_at` — Дата проверки цены (YYYY-MM-DD)

### resort_components.csv

Компоненты рейтинга (курорт × компонент). 160 строк, 8 полей.

- `resort_id` — справочное поле/ключ
- `name_ru` — справочное поле/ключ
- `region` — справочное поле/ключ
- `component` — справочное поле/ключ
- `component_name_ru` — справочное поле/ключ
- `component_weight` — справочное поле/ключ
- `component_score` — справочное поле/ключ
- `contribution` — справочное поле/ключ

### ranking_stability.csv

Устойчивость и локальный рейтинг для каждого пресета (курорт × пресет). 192 строк, 11 полей.

- `resort_id` — справочное поле/ключ
- `preset_id` — Пресет скоринга (—) — base / balance / infra / snow / access / price
- `preset_name_ru` — Название пресета (—) — Для фильтра «Пресет рейтинга»
- `name_ru` — справочное поле/ключ
- `region` — справочное поле/ключ
- `median_rank` — Медианное место (место) — По сценариям весов, не доверительный интервал
- `rank_p5` — Место, 5-й процентиль (место) — Диапазон мест в сценариях весов
- `rank_p95` — Место, 95-й процентиль (место) — Диапазон мест в сценариях весов
- `top10_frequency` — Частота топ-10 (доля 0–1) — Частота в заданных сценариях весов, не вероятность коммерческого успеха
- `local_score` — Локальный индекс (без региона) (баллы 0–100) — Взвешенная сумма 4 нерегиональных компонентов с весами пресета
- `local_rank` — Локальное место (без региона) (место)

### resort_reasons.csv

Объяснения «почему» (длинный формат: причина × строка). 89 строк, 5 полей.

- `resort_id` — справочное поле/ключ
- `name_ru` — справочное поле/ключ
- `reason_type` — справочное поле/ключ
- `reason_code` — справочное поле/ключ
- `reason_text` — справочное поле/ключ

### catalog_scenarios.csv

Сценарии каталога и их KPI. 72 строки (6 пресетов × 3 стратегии × 4 N), 16 полей.

- `scenario_id` — Идентификатор сценария (—) — Код вида {preset}_{strategy}_nN (например, infra_diversity_n10)
- `preset_id` — Пресет скоринга (—) — base / balance / infra / snow / access / price
- `preset_name_ru` — Пресет (название) (—)
- `strategy` — Стратегия (код) (—) — top / diversity / diversity_verified
- `strategy_name_ru` — Стратегия (название) (—)
- `scenario_label` — Читаемая подпись (—) — «стратегия · пресет · N=n»
- `n` — Размер каталога (курортов) — 5 / 8 / 10 / 12
- `max_per_region` — Макс. курортов на регион (шт.) — None для top, 1 для разнообразия
- `status` — Статус выполнимости (—) — feasible / infeasible
- `resort_count` — Курортов в каталоге (шт.) — Равно N для feasible
- `region_count` — Регионов в каталоге (шт.)
- `max_region_share` — Концентрация (макс. доля региона) (доля 0–1) — Наибольшее число курортов одного региона / N
- `avg_index` — Средний индекс каталога (баллы 0–100)
- `avg_index_vs_top` — Разница среднего с топ-N (баллы) — Отрицательное = уступаем топ-N
- `confirmed_coords_count` — С подтверждёнными координатами (шт.)
- `observed_price_count` — С наблюдаемой ценой (шт.)

### catalog_members.csv

Состав каталога по сценариям. 630 строк, 10 полей.

- `scenario_id` — Идентификатор сценария (—) — Код вида {preset}_{strategy}_nN
- `preset_id` — Пресет скоринга (—)
- `resort_id` — справочное поле/ключ
- `name_ru` — справочное поле/ключ
- `region` — справочное поле/ключ
- `scenario_score` — Балл курорта в пресете (баллы 0–100) — итоговый scenario_score пресета
- `scenario_rank` — Глобальное место в пресете (место) — 1..32 по scenario_score
- `rank_within_scenario` — Место внутри набора (место) — 1..N
- `coordinate_validation_status` — Статус валидации координат (—) — confirmed / provisional / needs_review
- `has_observed_price` — Есть наблюдаемая цена (—) — true/false

### climate_monthly.csv

Месячный климат ноябрь–апрель. 192 строк, 12 полей.

- `resort_id` — справочное поле/ключ
- `name_ru` — справочное поле/ключ
- `region` — справочное поле/ключ
- `month` — справочное поле/ключ
- `month_name_ru` — справочное поле/ключ
- `years_count` — справочное поле/ключ
- `mean_temperature_c` — справочное поле/ключ
- `avg_monthly_precipitation_mm` — справочное поле/ключ
- `avg_monthly_snowfall_cm` — справочное поле/ключ
- `avg_freezing_days` — справочное поле/ключ
- `avg_snow_days` — справочное поле/ключ
- `weather_model` — справочное поле/ключ

### weather_forecast_daily.csv

Прогноз 7 дней (курорт × дата). 224 строк, 19 полей.

- `resort_id` — справочное поле/ключ
- `name_ru` — справочное поле/ключ
- `region` — справочное поле/ключ
- `date` — Дата действия прогноза (YYYY-MM-DD)
- `fetched_at` — Время получения прогноза (ISO UTC) — Свежесть = текущее время − fetched_at, считается в BI
- `elevation_m` — Высота точки запроса (м)
- `resort_elevation_m` — Высота курорта (модель) (м)
- `snowfall_cm` — Снегопад (см)
- `rain_mm` — Жидкие осадки (мм)
- `temperature_min_c` — Температура (мин) (°C)
- `temperature_max_c` — Температура (макс) (°C)
- `weather_code` — Код погоды (WMO) (—)
- `wind_gusts_max_kmh` — Порывы ветра (км/ч) — Порывы не означают автоматическое закрытие подъёмников
- `snow_depth_m` — Модельная высота снега (м) — Не учитывает искусственное оснежение
- `freezing_level_min_m` — Минимальная высота изотермы 0°C (м)
- `slope_condition` — Состояние трассы (модель) (—) — Погодные предпосылки, не наблюдаемая поверхность
- `condition_reason` — Причина категории (—) — Из фактических условий правила
- `condition_limitations` — Ограничение оценки (—) — Чего оценка не учитывает
- `strong_wind` — Сильный ветер (—) — Порывы ≥ 50 км/ч

### atlas_catalog.csv

Единая витрина страницы 1 (широкий рейтинг + сценарии каталога). 732 строк, 86 полей.

Строки: `all_top` (полный рейтинг, 192 = 6 пресетов × 32 курорта), `all_diversity` (лучший курорт региона, 120), member-сценарии `top`/`diversity` (420). Собрана `build_atlas_catalog.py` из `resort_preset_components` (pivot), `resort_features`, `resort_scores`, `ranking_stability`, `presets`, `scoring_weights`.

Ключевые поля (сверх полей `resort_features`/`resort_scores`, перенесённых «как есть»):
- `scenario_id` — Идентификатор сценария (—) — `all_top` / `all_diversity` / `{preset}_{strategy}_nN`
- `scenario_label` — Подпись сценария (—)
- `strategy_name_ru` — Название стратегии (—)
- `size_label` — Размер набора (—) — «Все» / «5» / «8» / «10» / «12»
- `n` — Число курортов в наборе (—) — NULL для `all_top`/`all_diversity`
- `scenario_score` / `scenario_rank` — балл и место в пресете
- `base_score` / `base_rank` — балл и место базовой модели
- `rank_change` — изменение места относительно базы
- `has_observed_price` — есть наблюдаемая цена (true/false)
- `regional_score`…`price_score` / `*_contribution` — 5 компонентных баллов и вкладов
- `regional_weight`…`price_weight` / `w_*` — веса пресета и веса 13 показателей
- `stability_median_rank` / `local_score` / `local_rank` — из `ranking_stability` (мерж по `resort_id + preset_id`)
- `confidence_score` — полнота данных

## Группы полей (field_dictionary)

- **Рейтинг и качество** — Итоговый индекс, место и оценка полноты данных
- **Компоненты** — Пять укрупнённых компонентов (баллы 0–100)
- **Индикаторы** — Исходные показатели, из которых складываются компоненты
- **Устойчивость** — Метрики чувствительности места к весам и локальный рейтинг
- **Прогноз** — Семидневный прогноз погоды и модельная оценка поверхности
- **Каталог** — Сценарии стартового каталога и их показатели

