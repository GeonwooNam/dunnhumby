-- 목적: 최종 진단표와 시각화용 마트를 소규모 CSV로 내보낸다.
-- 입력: 00~08 단계의 audit/mart 테이블
-- 출력: product_axis_outputs/*.csv

COPY (SELECT * FROM audit_source_overview ORDER BY table_name)
TO 'product_axis_outputs/source_audit_overview.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_promo_codes ORDER BY promo_type, row_count DESC)
TO 'product_axis_outputs/source_audit_promo_codes.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_key_quality)
TO 'product_axis_outputs/source_audit_key_quality.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_store_coverage)
TO 'product_axis_outputs/source_audit_store_coverage.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_active_panel_size ORDER BY min_sold_weeks)
TO 'product_axis_outputs/source_audit_panel_size.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_store_variation ORDER BY promo_type)
TO 'product_axis_outputs/source_audit_store_variation.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_panel_structure)
TO 'product_axis_outputs/source_audit_panel_structure.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_store_week_traffic)
TO 'product_axis_outputs/source_audit_store_week_traffic.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_promo_2x2)
TO 'product_axis_outputs/promo_2x2_summary.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_promo_synergy)
TO 'product_axis_outputs/promo_synergy_summary.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_promo_traffic_strata)
TO 'product_axis_outputs/promo_traffic_strata.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_mailer_product_week_summary)
TO 'product_axis_outputs/mailer_product_week_summary.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_mailer_within_product_summary)
TO 'product_axis_outputs/mailer_within_product_summary.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_within_pair_summary)
TO 'product_axis_outputs/within_pair_summary.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_position_summary)
TO 'product_axis_outputs/position_summary.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_position_heatmap)
TO 'product_axis_outputs/position_heatmap.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_segment_response)
TO 'product_axis_outputs/category_brand_summary.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_weekly_promotion_trend)
TO 'product_axis_outputs/weekly_promotion_trend.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_event_trend)
TO 'product_axis_outputs/weekly_event_trend.csv' (FORMAT CSV, HEADER);
