-- 목적: 적격 선호상품 전체를 고정 분모로 사용한 고객-주 노출지표를 만든다.
-- 입력: work_customer_preference, work_relevant_promotion_clean
-- 출력: mart_customer_week_exposure와 노출 품질·분포·변동 감사표

CREATE OR REPLACE TABLE mart_customer_week_exposure AS
SELECT
    p.household_key,
    w.WEEK_NO,
    SUM(p.preference_weight_top20 * COALESCE(r.is_feature_mailer, 0))
        AS feature_mailer_exposure,
    SUM(p.preference_weight_top20 * COALESCE(r.is_display, 0))
        AS display_exposure,
    SUM(p.preference_weight_top20
        * CASE WHEN COALESCE(r.is_feature_mailer, 0) = 1
                AND COALESCE(r.is_display, 0) = 1
               THEN 1 ELSE 0 END) AS both_exposure,
    SUM(p.preference_weight_top20
        * CASE WHEN COALESCE(r.is_feature_mailer, 0) = 1
                OR COALESCE(r.is_display, 0) = 1
               THEN 1 ELSE 0 END) AS any_feature_exposure,
    SUM(p.preference_weight_top20 * COALESCE(r.is_coupon_mailer, 0))
        AS coupon_mailer_exposure,
    SUM(p.preference_weight_top20 * COALESCE(r.is_free_mailer, 0))
        AS free_mailer_exposure,
    SUM(p.preference_weight_top20 * COALESCE(r.is_any_mailer, 0))
        AS any_mailer_exposure,
    SUM(p.preference_weight_top20
        * CASE WHEN r.promotion_record_present = 1 THEN 1 ELSE 0 END)
        AS promo_record_weight,
    SUM(p.preference_weight_top20
        * COALESCE(r.promo_code_conflict, 0)) AS conflict_weight,
    SUM(p.preference_weight_top10
        * CASE WHEN COALESCE(r.is_feature_mailer, 0) = 1
                OR COALESCE(r.is_display, 0) = 1
               THEN 1 ELSE 0 END) AS any_feature_exposure_top10,
    SUM(p.preference_weight_top10 * COALESCE(r.is_feature_mailer, 0))
        AS feature_mailer_exposure_top10,
    SUM(p.preference_weight_top10 * COALESCE(r.is_display, 0))
        AS display_exposure_top10,
    SUM(p.preference_weight_top10
        * CASE WHEN COALESCE(r.is_feature_mailer, 0) = 1
                AND COALESCE(r.is_display, 0) = 1
               THEN 1 ELSE 0 END) AS both_exposure_top10
FROM work_customer_preference AS p
CROSS JOIN range(27, 102) AS w(WEEK_NO)
LEFT JOIN work_relevant_promotion_clean AS r
  ON p.PRODUCT_ID = r.PRODUCT_ID
 AND p.home_store_id = r.STORE_ID
 AND w.WEEK_NO = r.WEEK_NO
GROUP BY 1, 2;

CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_week_exposure
ON mart_customer_week_exposure (household_key, WEEK_NO);

-- 선호상품 적격성 규칙 자체가 결과를 좌우하는지 확인하는 세 가지 고정분모 노출.
CREATE OR REPLACE TABLE mart_eligibility_sensitivity_exposure AS
WITH preference_rows AS (
    SELECT
        'baseline_history_eligible5' AS sample_definition,
        p.household_key,
        p.PRODUCT_ID,
        p.home_store_id,
        p.preference_weight_top20
    FROM work_customer_preference AS p
    JOIN work_analysis_customer AS c USING (household_key)
    WHERE c.is_primary_analysis = 1
    UNION ALL
    SELECT
        'all_weeks_history_eligible5',
        p.household_key,
        p.PRODUCT_ID,
        p.home_store_id,
        p.preference_weight_top20
    FROM work_customer_preference_all_weeks AS p
    JOIN work_analysis_customer AS c USING (household_key)
    WHERE c.is_primary_all_weeks_analysis = 1
    UNION ALL
    SELECT
        'no_history_filter_eligible5',
        p.household_key,
        p.PRODUCT_ID,
        p.home_store_id,
        p.preference_weight_top20
    FROM work_customer_preference_no_history_filter AS p
    JOIN work_analysis_customer AS c USING (household_key)
    WHERE c.is_primary_no_history_filter_analysis = 1
)
SELECT
    p.sample_definition,
    p.household_key,
    w.WEEK_NO,
    SUM(
        p.preference_weight_top20
        * CASE WHEN COALESCE(r.is_feature_mailer, 0) = 1
                OR COALESCE(r.is_display, 0) = 1
               THEN 1 ELSE 0 END
    ) AS any_feature_exposure
FROM preference_rows AS p
CROSS JOIN range(27, 102) AS w(WEEK_NO)
LEFT JOIN work_relevant_promotion_clean AS r
  ON p.PRODUCT_ID = r.PRODUCT_ID
 AND p.home_store_id = r.STORE_ID
 AND w.WEEK_NO = r.WEEK_NO
GROUP BY 1, 2, 3;

CREATE OR REPLACE TABLE work_customer_week_exposure_long AS
SELECT
    e.household_key,
    e.WEEK_NO,
    x.exposure_type,
    x.exposure_value
FROM mart_customer_week_exposure AS e
CROSS JOIN LATERAL (
    VALUES
        ('any_feature', e.any_feature_exposure),
        ('feature_mailer', e.feature_mailer_exposure),
        ('display', e.display_exposure),
        ('both', e.both_exposure),
        ('coupon_mailer', e.coupon_mailer_exposure),
        ('free_mailer', e.free_mailer_exposure),
        ('any_mailer', e.any_mailer_exposure)
) AS x(exposure_type, exposure_value);

CREATE OR REPLACE TABLE audit_customer_exposure_distribution AS
WITH sample_exposure AS (
    SELECT 'candidate_top20' AS sample_definition,
           e.household_key, e.WEEK_NO, e.any_feature_exposure AS exposure
    FROM mart_customer_week_exposure AS e
    JOIN work_analysis_customer AS c USING (household_key)
    WHERE c.is_candidate_analysis = 1
    UNION ALL
    SELECT 'primary_top20', e.household_key, e.WEEK_NO,
           e.any_feature_exposure
    FROM mart_customer_week_exposure AS e
    JOIN work_analysis_customer AS c USING (household_key)
    WHERE c.is_primary_analysis = 1
    UNION ALL
    SELECT 'home70_top20', e.household_key, e.WEEK_NO,
           e.any_feature_exposure
    FROM mart_customer_week_exposure AS e
    JOIN work_analysis_customer AS c USING (household_key)
    WHERE c.is_home70_analysis = 1
    UNION ALL
    SELECT 'primary_top10', e.household_key, e.WEEK_NO,
           e.any_feature_exposure_top10
    FROM mart_customer_week_exposure AS e
    JOIN work_analysis_customer AS c USING (household_key)
    WHERE c.is_primary_analysis = 1
)
SELECT
    sample_definition,
    COUNT(DISTINCT household_key) AS households,
    COUNT(*) AS household_weeks,
    AVG(exposure) AS mean_exposure,
    STDDEV_SAMP(exposure) AS sd_exposure,
    QUANTILE_CONT(exposure, 0.10) AS p10,
    QUANTILE_CONT(exposure, 0.25) AS p25,
    MEDIAN(exposure) AS p50,
    QUANTILE_CONT(exposure, 0.75) AS p75,
    QUANTILE_CONT(exposure, 0.90) AS p90,
    AVG(CASE WHEN exposure = 0 THEN 1.0 ELSE 0.0 END)
        AS zero_exposure_rate
FROM sample_exposure
GROUP BY 1
ORDER BY 1;

CREATE OR REPLACE TABLE audit_customer_exposure_by_type AS
SELECT
    l.exposure_type,
    COUNT(DISTINCT l.household_key) AS households,
    COUNT(*) AS household_weeks,
    AVG(l.exposure_value) AS mean_exposure,
    STDDEV_SAMP(l.exposure_value) AS sd_exposure,
    MEDIAN(l.exposure_value) AS median_exposure,
    QUANTILE_CONT(l.exposure_value, 0.90) AS p90_exposure,
    AVG(CASE WHEN l.exposure_value = 0 THEN 1.0 ELSE 0.0 END)
        AS zero_exposure_rate
FROM work_customer_week_exposure_long AS l
JOIN work_analysis_customer AS c USING (household_key)
WHERE c.is_primary_analysis = 1
GROUP BY 1
ORDER BY 1;

CREATE OR REPLACE TABLE audit_customer_exposure_variation AS
WITH primary_exposure AS (
    SELECT l.*
    FROM work_customer_week_exposure_long AS l
    JOIN work_analysis_customer AS c USING (household_key)
    WHERE c.is_primary_analysis = 1
), customer_mean AS (
    SELECT
        household_key,
        exposure_type,
        AVG(exposure_value) AS customer_mean_exposure,
        STDDEV_SAMP(exposure_value) AS customer_sd_exposure
    FROM primary_exposure
    GROUP BY 1, 2
), deviations AS (
    SELECT
        p.exposure_type,
        p.household_key,
        p.exposure_value - c.customer_mean_exposure AS exposure_deviation
    FROM primary_exposure AS p
    JOIN customer_mean AS c USING (household_key, exposure_type)
)
SELECT
    c.exposure_type,
    COUNT(DISTINCT c.household_key) AS households,
    SQRT(AVG(d.exposure_deviation * d.exposure_deviation))
        AS pooled_within_customer_sd,
    STDDEV_SAMP(c.customer_mean_exposure) AS between_customer_sd,
    AVG(c.customer_sd_exposure) AS avg_customer_sd,
    AVG(CASE WHEN c.customer_sd_exposure > 0 THEN 1.0 ELSE 0.0 END)
        AS households_with_variation_rate
FROM customer_mean AS c
JOIN deviations AS d USING (household_key, exposure_type)
GROUP BY 1
ORDER BY 1;

CREATE OR REPLACE TABLE audit_customer_exposure_record_quality AS
SELECT
    COUNT(DISTINCT e.household_key) AS households,
    COUNT(*) AS household_weeks,
    AVG(e.promo_record_weight) AS avg_promo_record_weight,
    MEDIAN(e.promo_record_weight) AS median_promo_record_weight,
    QUANTILE_CONT(e.promo_record_weight, 0.90) AS p90_promo_record_weight,
    AVG(e.conflict_weight) AS avg_conflict_weight,
    MAX(e.conflict_weight) AS max_conflict_weight,
    AVG(CASE WHEN e.conflict_weight > 0 THEN 1.0 ELSE 0.0 END)
        AS conflict_household_week_rate,
    CORR(e.promo_record_weight, e.any_feature_exposure)
        AS record_weight_exposure_correlation
FROM mart_customer_week_exposure AS e
JOIN work_analysis_customer AS c USING (household_key)
WHERE c.is_primary_analysis = 1;

CREATE OR REPLACE TABLE audit_customer_exposure_histogram AS
SELECT
    LEAST(FLOOR(e.any_feature_exposure * 20) / 20.0, 1.0)
        AS exposure_bin_start,
    COUNT(*) AS household_weeks
FROM mart_customer_week_exposure AS e
JOIN work_analysis_customer AS c USING (household_key)
WHERE c.is_primary_analysis = 1
GROUP BY 1
ORDER BY 1;

CREATE OR REPLACE TABLE mart_customer_weekly_exposure_trend AS
SELECT
    e.WEEK_NO,
    COUNT(DISTINCT e.household_key) AS households,
    AVG(e.any_feature_exposure) AS avg_any_feature_exposure,
    AVG(e.feature_mailer_exposure) AS avg_feature_mailer_exposure,
    AVG(e.display_exposure) AS avg_display_exposure,
    AVG(e.both_exposure) AS avg_both_exposure,
    AVG(e.coupon_mailer_exposure) AS avg_coupon_mailer_exposure,
    AVG(e.free_mailer_exposure) AS avg_free_mailer_exposure
FROM mart_customer_week_exposure AS e
JOIN work_analysis_customer AS c USING (household_key)
WHERE c.is_primary_analysis = 1
GROUP BY 1
ORDER BY 1;
