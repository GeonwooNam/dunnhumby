-- 목적: 고객축 감사표와 결과표를 시각화·보고서용 CSV로 내보낸다.
-- 입력: 00~05 단계의 audit/mart 테이블
-- 출력: customer_axis_outputs/*.csv

COPY (SELECT * FROM audit_customer_source_overview ORDER BY table_name)
TO 'customer_axis_outputs/source_overview.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_week_calendar ORDER BY WEEK_NO)
TO 'customer_axis_outputs/week_calendar.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_entry_week ORDER BY entry_band)
TO 'customer_axis_outputs/entry_week.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_promo_codes ORDER BY code_type, code)
TO 'customer_axis_outputs/promo_codes.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_promo_key_quality)
TO 'customer_axis_outputs/promo_key_quality.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_campaign_overview ORDER BY campaign_type)
TO 'customer_axis_outputs/campaign_overview.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_transaction_quality)
TO 'customer_axis_outputs/transaction_quality.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_sample_flow ORDER BY step_no)
TO 'customer_axis_outputs/sample_flow.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_candidate_definition ORDER BY candidate_definition)
TO 'customer_axis_outputs/candidate_definition.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_baseline_weeks ORDER BY baseline_week_band)
TO 'customer_axis_outputs/baseline_weeks.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_home_store_share ORDER BY period)
TO 'customer_axis_outputs/home_store_share.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_preference_exclusion)
TO 'customer_axis_outputs/preference_exclusion.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_preference_summary ORDER BY sample_definition)
TO 'customer_axis_outputs/preference_summary.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_preference_count_band ORDER BY eligible_product_band)
TO 'customer_axis_outputs/preference_count_band.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_exposure_distribution ORDER BY sample_definition)
TO 'customer_axis_outputs/exposure_distribution.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_exposure_by_type ORDER BY exposure_type)
TO 'customer_axis_outputs/exposure_by_type.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_exposure_variation ORDER BY exposure_type)
TO 'customer_axis_outputs/exposure_variation.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_exposure_record_quality)
TO 'customer_axis_outputs/exposure_record_quality.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_exposure_histogram ORDER BY exposure_bin_start)
TO 'customer_axis_outputs/exposure_histogram.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_customer_weekly_exposure_trend ORDER BY WEEK_NO)
TO 'customer_axis_outputs/weekly_exposure_trend.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_state_distribution ORDER BY visit_gap_band)
TO 'customer_axis_outputs/state_distribution.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_campaign_overlap ORDER BY active_campaign_band)
TO 'customer_axis_outputs/campaign_overlap.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_customer_panel_outcome)
TO 'customer_axis_outputs/panel_outcome.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_raw_exposure_response ORDER BY exposure_quartile)
TO 'customer_axis_outputs/raw_exposure_response.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_within_customer_response ORDER BY exposure_type, deviation_quartile)
TO 'customer_axis_outputs/within_customer_response.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_within_customer_high_low ORDER BY exposure_type)
TO 'customer_axis_outputs/within_customer_high_low.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_two_way_centered_response ORDER BY exposure_type, double_centered_quartile)
TO 'customer_axis_outputs/two_way_centered_response.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_sample_sensitivity ORDER BY sample_definition)
TO 'customer_axis_outputs/sample_sensitivity.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_campaign_sensitivity ORDER BY campaign_segment)
TO 'customer_axis_outputs/campaign_sensitivity.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_visit_gap_exposure_response
      ORDER BY campaign_segment, visit_gap_band, exposure_quartile)
TO 'customer_axis_outputs/visit_gap_exposure_response.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_visit_gap_within_response ORDER BY visit_gap_band)
TO 'customer_axis_outputs/visit_gap_within_response.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_department_response ORDER BY department_relation, exposure_state)
TO 'customer_axis_outputs/department_response.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_department_within_response ORDER BY department_relation)
TO 'customer_axis_outputs/department_within_response.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_department_detail
      ORDER BY comparable_households DESC, DEPARTMENT, department_relation)
TO 'customer_axis_outputs/department_detail.csv' (FORMAT CSV, HEADER);

COPY (
    SELECT
        household_key,
        is_candidate_analysis,
        is_primary_analysis,
        is_primary_eligible1_analysis,
        is_primary_all_weeks_analysis,
        is_primary_no_history_filter_analysis,
        is_home70_analysis,
        first_observed_week,
        baseline_baskets,
        n_baseline_purchase_weeks,
        baseline_weekly_visit_rate,
        home_store_id,
        baseline_home_store_share,
        outcome_home_store_share,
        n_eligible_products,
        n_eligible_products_all_weeks,
        n_repeated_products_no_history_filter,
        original_top20_baskets,
        eligible_original_top20_baskets,
        excluded_weight_share
    FROM work_analysis_customer
    WHERE is_candidate_analysis = 1
    ORDER BY household_key
)
TO 'customer_axis_outputs/customer_sample.csv' (FORMAT CSV, HEADER);
