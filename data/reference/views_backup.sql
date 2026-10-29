-- DDL backup: 2026-10-28T14:37:03.873725Z

-- ===== atlas_summary =====
CREATE OR REPLACE VIEW public.atlas_summary AS
 SELECT rf.resort_id,
    rf.name_ru,
    rf.region,
    rf.latitude,
    rf.longitude,
    round(ac.base_score::numeric, 1) AS index_score,
    ac.base_rank AS index_rank,
    round(ac.confidence_score::numeric, 1) AS quality_score,
    round(ac.regional_contribution::numeric, 1) AS regional_contribution,
    round(ac.infrastructure_contribution::numeric, 1) AS infrastructure_contribution,
    round(ac.winter_contribution::numeric, 1) AS winter_contribution,
    round(ac.accessibility_contribution::numeric, 1) AS accessibility_contribution,
    round(ac.price_contribution::numeric, 1) AS price_contribution,
    round(rf.adult_skipass_avg_rub::numeric, 0) AS price_rub,
    rf.price_months_count,
    rf.price_product,
    rf.price_season,
    round(rf.winter_mean_temperature_c::numeric, 1) AS climate_mean_temp_c,
    round(rf.avg_snowfall_cm_per_season::numeric, 0) AS climate_snowfall_cm,
    round(rf.avg_snow_days_per_season::numeric, 0) AS climate_snow_days,
    round(rf.avg_freezing_days_per_season::numeric, 0) AS climate_freezing_days,
    rf.nearest_airport_distance_km AS airport_km,
    rf.nearest_airport_iata AS airport_iata,
    rf.piste_min_elevation_m,
    rf.piste_max_elevation_m,
    rf.piste_max_elevation_m - rf.piste_min_elevation_m AS elevation_drop,
    rf.piste_length_km,
    rf.piste_ways_total,
    rf.lift_lines_6km,
    rf.piste_type_snow_park,
    rf.piste_type_nordic,
    rf.piste_difficulty_novice AS diff_novice_km,
    rf.piste_difficulty_easy AS diff_easy_km,
    rf.piste_difficulty_intermediate AS diff_intermediate_km,
    rf.piste_difficulty_advanced AS diff_advanced_km,
    rf.piste_difficulty_expert AS diff_expert_km,
    rf.piste_difficulty_freeride AS diff_freeride_km,
    rf.piste_difficulty_unknown AS diff_unknown_km,
    rf.lodging_objects_6km,
    rf.food_objects_6km,
    rf.attraction_objects_6km,
    rf.transport_objects_6km,
    rf.details_url,
    rf.details_url_source,
    rf.official_website_url,
    COALESCE(NULLIF(rf.skimap_url, ''::text),
        CASE
            WHEN rf.openskimap_sources ~ 'skimap\.org:[0-9]+'::text THEN 'https://skimap.org/skiareas/view/'::text || "substring"(rf.openskimap_sources, 'skimap\.org:([0-9]+)'::text)
            ELSE 'https://skimap.org'::text
        END) AS skimap_url,
    ( SELECT string_agg(rr.reason_text, '; '::text ORDER BY rr.reason_text) AS string_agg
           FROM resort_reasons rr
          WHERE rr.resort_id = rf.resort_id AND rr.reason_type = 'strength'::text) AS strengths_text,
    ( SELECT string_agg(rr.reason_text, '; '::text ORDER BY rr.reason_text) AS string_agg
           FROM resort_reasons rr
          WHERE rr.resort_id = rf.resort_id AND rr.reason_type = 'weakness'::text) AS weaknesses_text,
    rs.region_trips_score,
    rs.region_growth_score,
    rs.avg_stay_score,
    rs.pistes_score,
    rs.lifts_score,
    rs.lodging_score,
    rs.amenities_score,
    rs.snow_days_score,
    rs.freezing_days_score,
    rs.snowfall_score,
    rs.airport_score,
    rs.transport_score,
    rs.price_score,
    round((rs.region_trips_score * w_rt.indicator_weight / 100.0::double precision)::numeric, 1) AS contrib_region_trips,
    round((rs.region_growth_score * w_rg.indicator_weight / 100.0::double precision)::numeric, 1) AS contrib_region_growth,
    round((rs.avg_stay_score * w_as.indicator_weight / 100.0::double precision)::numeric, 1) AS contrib_avg_stay,
    round((rs.pistes_score * w_p.indicator_weight / 100.0::double precision)::numeric, 1) AS contrib_pistes,
    round((rs.lifts_score * w_l.indicator_weight / 100.0::double precision)::numeric, 1) AS contrib_lifts,
    round((rs.lodging_score * w_lo.indicator_weight / 100.0::double precision)::numeric, 1) AS contrib_lodging,
    round((rs.amenities_score * w_am.indicator_weight / 100.0::double precision)::numeric, 1) AS contrib_amenities,
    round((rs.snow_days_score * w_sd.indicator_weight / 100.0::double precision)::numeric, 1) AS contrib_snow_days,
    round((rs.freezing_days_score * w_fd.indicator_weight / 100.0::double precision)::numeric, 1) AS contrib_freezing_days,
    round((rs.snowfall_score * w_sf.indicator_weight / 100.0::double precision)::numeric, 1) AS contrib_snowfall,
    round((rs.airport_score * w_ap.indicator_weight / 100.0::double precision)::numeric, 1) AS contrib_airport,
    round((rs.transport_score * w_tr.indicator_weight / 100.0::double precision)::numeric, 1) AS contrib_transport,
    round((rs.price_score * w_pr.indicator_weight / 100.0::double precision)::numeric, 1) AS contrib_price
   FROM resort_features rf
     JOIN atlas_catalog ac ON ac.resort_id = rf.resort_id AND ac.preset_id = 'base'::text AND ac.scenario_id = 'all_top'::text
     LEFT JOIN resort_scores rs ON rs.resort_id = rf.resort_id
     LEFT JOIN scoring_weights w_rt ON w_rt.indicator = 'region_trips'::text
     LEFT JOIN scoring_weights w_rg ON w_rg.indicator = 'region_growth'::text
     LEFT JOIN scoring_weights w_as ON w_as.indicator = 'avg_stay'::text
     LEFT JOIN scoring_weights w_p ON w_p.indicator = 'pistes'::text
     LEFT JOIN scoring_weights w_l ON w_l.indicator = 'lifts'::text
     LEFT JOIN scoring_weights w_lo ON w_lo.indicator = 'lodging'::text
     LEFT JOIN scoring_weights w_am ON w_am.indicator = 'amenities'::text
     LEFT JOIN scoring_weights w_sd ON w_sd.indicator = 'snow_days'::text
     LEFT JOIN scoring_weights w_fd ON w_fd.indicator = 'freezing_days'::text
     LEFT JOIN scoring_weights w_sf ON w_sf.indicator = 'snowfall'::text
     LEFT JOIN scoring_weights w_ap ON w_ap.indicator = 'airport'::text
     LEFT JOIN scoring_weights w_tr ON w_tr.indicator = 'transport'::text
     LEFT JOIN scoring_weights w_pr ON w_pr.indicator = 'price'::text;;


-- ===== v_index_breakdown =====
CREATE OR REPLACE VIEW public.v_index_breakdown AS
 WITH unpivoted AS (
         SELECT atlas_summary.name_ru,
            'Регион'::text AS component,
            'Поездки'::text AS indicator,
            atlas_summary.region_trips_score AS score,
            'region_trips'::text AS code
           FROM atlas_summary
        UNION ALL
         SELECT atlas_summary.name_ru,
            'Регион'::text,
            'Рост поездок'::text,
            atlas_summary.region_growth_score,
            'region_growth'::text
           FROM atlas_summary
        UNION ALL
         SELECT atlas_summary.name_ru,
            'Регион'::text,
            'Длительность'::text,
            atlas_summary.avg_stay_score,
            'avg_stay'::text
           FROM atlas_summary
        UNION ALL
         SELECT atlas_summary.name_ru,
            'Инфра'::text,
            'Трассы'::text,
            atlas_summary.pistes_score,
            'pistes'::text
           FROM atlas_summary
        UNION ALL
         SELECT atlas_summary.name_ru,
            'Инфра'::text,
            'Подъёмники'::text,
            atlas_summary.lifts_score,
            'lifts'::text
           FROM atlas_summary
        UNION ALL
         SELECT atlas_summary.name_ru,
            'Инфра'::text,
            'Размещение'::text,
            atlas_summary.lodging_score,
            'lodging'::text
           FROM atlas_summary
        UNION ALL
         SELECT atlas_summary.name_ru,
            'Инфра'::text,
            'Питание и досуг'::text,
            atlas_summary.amenities_score,
            'amenities'::text
           FROM atlas_summary
        UNION ALL
         SELECT atlas_summary.name_ru,
            'Зима'::text,
            'Снежные дни'::text,
            atlas_summary.snow_days_score,
            'snow_days'::text
           FROM atlas_summary
        UNION ALL
         SELECT atlas_summary.name_ru,
            'Зима'::text,
            'Морозные дни'::text,
            atlas_summary.freezing_days_score,
            'freezing_days'::text
           FROM atlas_summary
        UNION ALL
         SELECT atlas_summary.name_ru,
            'Зима'::text,
            'Снегопад'::text,
            atlas_summary.snowfall_score,
            'snowfall'::text
           FROM atlas_summary
        UNION ALL
         SELECT atlas_summary.name_ru,
            'Доступ'::text,
            'Аэропорт'::text,
            atlas_summary.airport_score,
            'airport'::text
           FROM atlas_summary
        UNION ALL
         SELECT atlas_summary.name_ru,
            'Доступ'::text,
            'Транспорт'::text,
            atlas_summary.transport_score,
            'transport'::text
           FROM atlas_summary
        UNION ALL
         SELECT atlas_summary.name_ru,
            'Цена'::text,
            'Цена'::text,
            atlas_summary.price_score,
            'price'::text
           FROM atlas_summary
        )
 SELECT u.name_ru,
    u.component,
    u.indicator,
    u.score AS raw_score,
    round((u.score * w.indicator_weight / 100.0::double precision)::numeric, 1) AS contribution
   FROM unpivoted u
     JOIN scoring_weights w ON w.indicator = u.code;;
