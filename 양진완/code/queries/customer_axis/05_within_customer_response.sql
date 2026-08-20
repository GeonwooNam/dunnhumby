-- 목적: 동일 고객 내 노출 편차와 방문·수취액 편차를 요약하고 방문 공백·부문별 결과를 만든다.
-- 입력: mart_customer_week_exposure, mart_customer_week_panel, 부문 선호·결과
-- 출력: mart_*_response 결과표

CREATE OR REPLACE TABLE work_customer_response_base AS
SELECT
    p.*,
    e.feature_mailer_exposure,
    e.display_exposure,
    e.both_exposure,
    e.any_feature_exposure,
    e.coupon_mailer_exposure,
    e.free_mailer_exposure,
    e.any_mailer_exposure,
    e.any_feature_exposure_top10,
    e.promo_record_weight,
    e.conflict_weight
FROM mart_customer_week_panel AS p
JOIN mart_customer_week_exposure AS e USING (household_key, WEEK_NO);

CREATE OR REPLACE TABLE mart_raw_exposure_response AS
WITH quartiled AS (
    SELECT
        *,
        NTILE(4) OVER (
            ORDER BY any_feature_exposure, WEEK_NO, household_key
        ) AS exposure_quartile
    FROM work_customer_response_base
    WHERE is_primary_analysis = 1
)
SELECT
    exposure_quartile,
    COUNT(DISTINCT household_key) AS households,
    COUNT(*) AS household_weeks,
    AVG(any_feature_exposure) AS avg_any_feature_exposure,
    AVG(feature_mailer_exposure) AS avg_feature_mailer_exposure,
    AVG(display_exposure) AS avg_display_exposure,
    AVG(both_exposure) AS avg_both_exposure,
    AVG(visit) AS visit_rate,
    AVG(home_store_visit) AS home_store_visit_rate,
    AVG(sales_value) AS avg_weekly_sales_value,
    AVG(sales_value) FILTER (WHERE visit = 1) AS avg_sales_per_visit_week,
    AVG(baskets) AS avg_baskets,
    AVG(CASE WHEN active_campaign_count > 0 THEN 1.0 ELSE 0.0 END)
        AS active_campaign_week_rate,
    AVG(weeks_since_last_visit) AS avg_weeks_since_last_visit
FROM quartiled
GROUP BY 1
ORDER BY 1;

CREATE OR REPLACE TABLE work_customer_response_long AS
SELECT
    b.household_key,
    b.WEEK_NO,
    l.exposure_type,
    l.exposure_value,
    b.visit,
    b.home_store_visit,
    b.baskets,
    b.sales_value,
    b.home_store_sales_value,
    b.weeks_since_last_visit,
    b.visit_gap_band,
    b.recent_8w_frequency_decline,
    b.active_campaign_count,
    b.ever_campaign_recipient
FROM work_customer_response_base AS b
JOIN work_customer_week_exposure_long AS l
  ON b.household_key = l.household_key
 AND b.WEEK_NO = l.WEEK_NO
WHERE b.is_primary_analysis = 1;

CREATE OR REPLACE TABLE work_customer_response_centered AS
WITH means AS (
    SELECT
        *,
        AVG(exposure_value) OVER (
            PARTITION BY household_key, exposure_type
        ) AS customer_mean_exposure,
        AVG(visit) OVER (
            PARTITION BY household_key, exposure_type
        ) AS customer_mean_visit,
        AVG(sales_value) OVER (
            PARTITION BY household_key, exposure_type
        ) AS customer_mean_sales,
        AVG(home_store_visit) OVER (
            PARTITION BY household_key, exposure_type
        ) AS customer_mean_home_store_visit,
        AVG(home_store_sales_value) OVER (
            PARTITION BY household_key, exposure_type
        ) AS customer_mean_home_store_sales,
        AVG(exposure_value) OVER (
            PARTITION BY WEEK_NO, exposure_type
        ) AS week_mean_exposure,
        AVG(visit) OVER (
            PARTITION BY WEEK_NO, exposure_type
        ) AS week_mean_visit,
        AVG(sales_value) OVER (
            PARTITION BY WEEK_NO, exposure_type
        ) AS week_mean_sales,
        AVG(home_store_visit) OVER (
            PARTITION BY WEEK_NO, exposure_type
        ) AS week_mean_home_store_visit,
        AVG(home_store_sales_value) OVER (
            PARTITION BY WEEK_NO, exposure_type
        ) AS week_mean_home_store_sales,
        AVG(exposure_value) OVER (PARTITION BY exposure_type)
            AS grand_mean_exposure,
        AVG(visit) OVER (PARTITION BY exposure_type)
            AS grand_mean_visit,
        AVG(sales_value) OVER (PARTITION BY exposure_type)
            AS grand_mean_sales,
        AVG(home_store_visit) OVER (PARTITION BY exposure_type)
            AS grand_mean_home_store_visit,
        AVG(home_store_sales_value) OVER (PARTITION BY exposure_type)
            AS grand_mean_home_store_sales
    FROM work_customer_response_long
)
SELECT
    *,
    exposure_value - customer_mean_exposure AS exposure_deviation,
    visit - customer_mean_visit AS visit_deviation,
    sales_value - customer_mean_sales AS sales_deviation,
    home_store_visit - customer_mean_home_store_visit
        AS home_store_visit_deviation,
    home_store_sales_value - customer_mean_home_store_sales
        AS home_store_sales_deviation,
    exposure_value - customer_mean_exposure - week_mean_exposure
        + grand_mean_exposure AS exposure_double_centered,
    visit - customer_mean_visit - week_mean_visit
        + grand_mean_visit AS visit_double_centered,
    sales_value - customer_mean_sales - week_mean_sales
        + grand_mean_sales AS sales_double_centered,
    home_store_visit - customer_mean_home_store_visit
        - week_mean_home_store_visit + grand_mean_home_store_visit
        AS home_store_visit_double_centered,
    home_store_sales_value - customer_mean_home_store_sales
        - week_mean_home_store_sales + grand_mean_home_store_sales
        AS home_store_sales_double_centered
FROM means;

CREATE OR REPLACE TABLE mart_within_customer_response AS
WITH quartiled AS (
    SELECT
        *,
        NTILE(4) OVER (
            PARTITION BY exposure_type
            ORDER BY exposure_deviation, WEEK_NO, household_key
        ) AS deviation_quartile
    FROM work_customer_response_centered
)
SELECT
    exposure_type,
    deviation_quartile,
    COUNT(DISTINCT household_key) AS households,
    COUNT(*) AS household_weeks,
    AVG(exposure_value) AS avg_exposure,
    AVG(exposure_deviation) AS avg_exposure_deviation,
    AVG(visit) AS raw_visit_rate,
    100 * AVG(visit_deviation) AS visit_deviation_pct_point,
    AVG(sales_value) AS raw_weekly_sales_value,
    AVG(sales_deviation) AS sales_value_deviation,
    AVG(CASE WHEN active_campaign_count > 0 THEN 1.0 ELSE 0.0 END)
        AS active_campaign_week_rate
FROM quartiled
GROUP BY 1, 2
ORDER BY 1, 2;

CREATE OR REPLACE TABLE mart_within_customer_high_low AS
WITH household_comparison AS (
    SELECT
        household_key,
        exposure_type,
        COUNT(*) FILTER (WHERE exposure_deviation > 1e-9) AS high_weeks,
        COUNT(*) FILTER (WHERE exposure_deviation < -1e-9) AS low_weeks,
        AVG(exposure_value) FILTER (WHERE exposure_deviation > 1e-9)
            AS high_exposure,
        AVG(exposure_value) FILTER (WHERE exposure_deviation < -1e-9)
            AS low_exposure,
        AVG(visit) FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(visit) FILTER (WHERE exposure_deviation < -1e-9)
            AS visit_rate_difference,
        AVG(sales_value) FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(sales_value) FILTER (WHERE exposure_deviation < -1e-9)
            AS sales_value_difference,
        AVG(home_store_visit) FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(home_store_visit) FILTER (WHERE exposure_deviation < -1e-9)
            AS home_store_visit_rate_difference,
        AVG(home_store_sales_value) FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(home_store_sales_value)
                FILTER (WHERE exposure_deviation < -1e-9)
            AS home_store_sales_value_difference,
        AVG(week_mean_visit) FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(week_mean_visit) FILTER (WHERE exposure_deviation < -1e-9)
            AS calendar_visit_difference,
        AVG(week_mean_sales) FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(week_mean_sales) FILTER (WHERE exposure_deviation < -1e-9)
            AS calendar_sales_difference,
        AVG(week_mean_home_store_visit)
            FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(week_mean_home_store_visit)
                FILTER (WHERE exposure_deviation < -1e-9)
            AS calendar_home_store_visit_difference,
        AVG(week_mean_home_store_sales)
            FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(week_mean_home_store_sales)
                FILTER (WHERE exposure_deviation < -1e-9)
            AS calendar_home_store_sales_difference
    FROM work_customer_response_centered
    GROUP BY 1, 2
    HAVING high_weeks > 0
       AND low_weeks > 0
       AND (exposure_type <> 'both' OR high_weeks >= 5)
)
SELECT
    exposure_type,
    COUNT(*) AS comparable_households,
    AVG(high_weeks) AS avg_high_weeks,
    AVG(low_weeks) AS avg_low_weeks,
    AVG(high_exposure) AS avg_high_exposure,
    AVG(low_exposure) AS avg_low_exposure,
    100 * AVG(visit_rate_difference) AS mean_visit_difference_pct_point,
    100 * STDDEV_SAMP(visit_rate_difference) / SQRT(COUNT(*))
        AS visit_difference_standard_error_pct_point,
    100 * MEDIAN(visit_rate_difference) AS median_visit_difference_pct_point,
    AVG(sales_value_difference) AS mean_sales_value_difference,
    STDDEV_SAMP(sales_value_difference) / SQRT(COUNT(*))
        AS sales_difference_standard_error,
    MEDIAN(sales_value_difference) AS median_sales_value_difference,
    100 * AVG(home_store_visit_rate_difference)
        AS mean_home_store_visit_difference_pct_point,
    100 * STDDEV_SAMP(home_store_visit_rate_difference) / SQRT(COUNT(*))
        AS home_store_visit_difference_standard_error_pct_point,
    AVG(home_store_sales_value_difference)
        AS mean_home_store_sales_value_difference,
    STDDEV_SAMP(home_store_sales_value_difference) / SQRT(COUNT(*))
        AS home_store_sales_difference_standard_error,
    100 * AVG(calendar_visit_difference)
        AS calendar_placebo_visit_difference_pct_point,
    AVG(calendar_sales_difference) AS calendar_placebo_sales_difference,
    100 * AVG(visit_rate_difference - calendar_visit_difference)
        AS net_calendar_visit_difference_pct_point,
    100 * STDDEV_SAMP(visit_rate_difference - calendar_visit_difference)
        / SQRT(COUNT(*))
        AS net_calendar_visit_difference_standard_error_pct_point,
    AVG(sales_value_difference - calendar_sales_difference)
        AS net_calendar_sales_difference,
    STDDEV_SAMP(sales_value_difference - calendar_sales_difference)
        / SQRT(COUNT(*)) AS net_calendar_sales_difference_standard_error,
    100 * AVG(calendar_home_store_visit_difference)
        AS calendar_placebo_home_store_visit_difference_pct_point,
    AVG(calendar_home_store_sales_difference)
        AS calendar_placebo_home_store_sales_difference,
    100 * AVG(
        home_store_visit_rate_difference
        - calendar_home_store_visit_difference
    ) AS net_calendar_home_store_visit_difference_pct_point,
    100 * STDDEV_SAMP(
        home_store_visit_rate_difference
        - calendar_home_store_visit_difference
    ) / SQRT(COUNT(*))
        AS net_calendar_home_store_visit_difference_standard_error_pct_point,
    AVG(
        home_store_sales_value_difference
        - calendar_home_store_sales_difference
    ) AS net_calendar_home_store_sales_difference,
    STDDEV_SAMP(
        home_store_sales_value_difference
        - calendar_home_store_sales_difference
    ) / SQRT(COUNT(*))
        AS net_calendar_home_store_sales_difference_standard_error,
    100 * AVG(CASE WHEN visit_rate_difference > 0 THEN 1.0 ELSE 0.0 END)
        AS households_positive_visit_difference_pct,
    100 * AVG(CASE WHEN sales_value_difference > 0 THEN 1.0 ELSE 0.0 END)
        AS households_positive_sales_difference_pct
FROM household_comparison
GROUP BY 1
ORDER BY 1;

CREATE OR REPLACE TABLE mart_two_way_centered_response AS
WITH quartiled AS (
    SELECT
        *,
        NTILE(4) OVER (
            PARTITION BY exposure_type
            ORDER BY exposure_double_centered, WEEK_NO, household_key
        ) AS double_centered_quartile
    FROM work_customer_response_centered
)
SELECT
    exposure_type,
    double_centered_quartile,
    COUNT(DISTINCT household_key) AS households,
    COUNT(*) AS household_weeks,
    AVG(exposure_double_centered) AS avg_exposure_double_centered,
    100 * AVG(visit_double_centered) AS visit_double_centered_pct_point,
    AVG(sales_double_centered) AS sales_double_centered
FROM quartiled
GROUP BY 1, 2
ORDER BY 1, 2;

CREATE OR REPLACE TABLE mart_sample_sensitivity AS
WITH sample_values AS (
    SELECT 'candidate_top20' AS sample_definition,
           household_key, WEEK_NO, any_feature_exposure AS exposure,
           visit, home_store_visit, sales_value, home_store_sales_value
    FROM work_customer_response_base
    WHERE is_candidate_analysis = 1
    UNION ALL
    SELECT 'primary_top20', household_key, WEEK_NO,
           any_feature_exposure, visit, home_store_visit,
           sales_value, home_store_sales_value
    FROM work_customer_response_base
    WHERE is_primary_analysis = 1
    UNION ALL
    SELECT 'primary_eligible1_top20', household_key, WEEK_NO,
           any_feature_exposure, visit, home_store_visit,
           sales_value, home_store_sales_value
    FROM work_customer_response_base
    WHERE is_primary_eligible1_analysis = 1
    UNION ALL
    SELECT 'home70_top20', household_key, WEEK_NO,
           any_feature_exposure, visit, home_store_visit,
           sales_value, home_store_sales_value
    FROM work_customer_response_base
    WHERE is_home70_analysis = 1
    UNION ALL
    SELECT 'primary_top10', household_key, WEEK_NO,
           any_feature_exposure_top10, visit, home_store_visit,
           sales_value, home_store_sales_value
    FROM work_customer_response_base
    WHERE is_primary_analysis = 1
    UNION ALL
    SELECT
        e.sample_definition,
        e.household_key,
        e.WEEK_NO,
        e.any_feature_exposure,
        p.visit,
        p.home_store_visit,
        p.sales_value,
        p.home_store_sales_value
    FROM mart_eligibility_sensitivity_exposure AS e
    JOIN mart_customer_week_panel AS p USING (household_key, WEEK_NO)
), centered AS (
    SELECT
        *,
        exposure - AVG(exposure) OVER (
            PARTITION BY sample_definition, household_key
        ) AS exposure_deviation
    FROM sample_values
), household_comparison AS (
    SELECT
        sample_definition,
        household_key,
        AVG(exposure) FILTER (WHERE exposure_deviation > 1e-9)
            AS high_exposure,
        AVG(exposure) FILTER (WHERE exposure_deviation < -1e-9)
            AS low_exposure,
        AVG(visit) FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(visit) FILTER (WHERE exposure_deviation < -1e-9)
            AS visit_rate_difference,
        AVG(home_store_visit) FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(home_store_visit) FILTER (WHERE exposure_deviation < -1e-9)
            AS home_store_visit_rate_difference,
        AVG(sales_value) FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(sales_value) FILTER (WHERE exposure_deviation < -1e-9)
            AS sales_value_difference,
        AVG(home_store_sales_value) FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(home_store_sales_value)
                FILTER (WHERE exposure_deviation < -1e-9)
            AS home_store_sales_value_difference,
        COUNT(*) FILTER (WHERE exposure_deviation > 1e-9) AS high_weeks,
        COUNT(*) FILTER (WHERE exposure_deviation < -1e-9) AS low_weeks
    FROM centered
    GROUP BY 1, 2
    HAVING high_weeks > 0 AND low_weeks > 0
)
SELECT
    sample_definition,
    COUNT(*) AS comparable_households,
    AVG(high_exposure) AS avg_high_exposure,
    AVG(low_exposure) AS avg_low_exposure,
    100 * AVG(visit_rate_difference) AS mean_visit_difference_pct_point,
    100 * STDDEV_SAMP(visit_rate_difference) / SQRT(COUNT(*))
        AS visit_difference_standard_error_pct_point,
    100 * AVG(home_store_visit_rate_difference)
        AS mean_home_store_visit_difference_pct_point,
    100 * STDDEV_SAMP(home_store_visit_rate_difference) / SQRT(COUNT(*))
        AS home_store_visit_difference_standard_error_pct_point,
    AVG(sales_value_difference) AS mean_sales_value_difference,
    STDDEV_SAMP(sales_value_difference) / SQRT(COUNT(*))
        AS sales_difference_standard_error,
    AVG(home_store_sales_value_difference)
        AS mean_home_store_sales_value_difference,
    STDDEV_SAMP(home_store_sales_value_difference) / SQRT(COUNT(*))
        AS home_store_sales_difference_standard_error,
    100 * AVG(CASE WHEN visit_rate_difference > 0 THEN 1.0 ELSE 0.0 END)
        AS households_positive_visit_difference_pct,
    100 * AVG(CASE WHEN sales_value_difference > 0 THEN 1.0 ELSE 0.0 END)
        AS households_positive_sales_difference_pct
FROM household_comparison
GROUP BY 1
ORDER BY 1;

CREATE OR REPLACE TABLE mart_campaign_sensitivity AS
WITH segment_rows AS (
    SELECT 'all_primary_weeks' AS campaign_segment, *
    FROM work_customer_response_base
    WHERE is_primary_analysis = 1
    UNION ALL
    SELECT 'campaign_inactive_weeks', *
    FROM work_customer_response_base
    WHERE is_primary_analysis = 1 AND active_campaign_count = 0
    UNION ALL
    SELECT 'campaign_active_weeks', *
    FROM work_customer_response_base
    WHERE is_primary_analysis = 1 AND active_campaign_count > 0
    UNION ALL
    SELECT 'never_campaign_recipient', *
    FROM work_customer_response_base
    WHERE is_primary_analysis = 1 AND ever_campaign_recipient = 0
), centered AS (
    SELECT
        *,
        any_feature_exposure - AVG(any_feature_exposure) OVER (
            PARTITION BY campaign_segment, household_key
        ) AS exposure_deviation
    FROM segment_rows
), household_comparison AS (
    SELECT
        campaign_segment,
        household_key,
        COUNT(*) FILTER (WHERE exposure_deviation > 1e-9) AS high_weeks,
        COUNT(*) FILTER (WHERE exposure_deviation < -1e-9) AS low_weeks,
        AVG(any_feature_exposure) FILTER (WHERE exposure_deviation > 1e-9)
            AS high_exposure,
        AVG(any_feature_exposure) FILTER (WHERE exposure_deviation < -1e-9)
            AS low_exposure,
        AVG(visit) FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(visit) FILTER (WHERE exposure_deviation < -1e-9)
            AS visit_rate_difference,
        AVG(home_store_visit) FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(home_store_visit) FILTER (WHERE exposure_deviation < -1e-9)
            AS home_store_visit_rate_difference,
        AVG(sales_value) FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(sales_value) FILTER (WHERE exposure_deviation < -1e-9)
            AS sales_value_difference,
        AVG(home_store_sales_value) FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(home_store_sales_value)
                FILTER (WHERE exposure_deviation < -1e-9)
            AS home_store_sales_value_difference
    FROM centered
    GROUP BY 1, 2
    HAVING high_weeks > 0 AND low_weeks > 0
)
SELECT
    campaign_segment,
    COUNT(*) AS comparable_households,
    AVG(high_exposure) AS avg_high_exposure,
    AVG(low_exposure) AS avg_low_exposure,
    100 * AVG(visit_rate_difference) AS mean_visit_difference_pct_point,
    100 * STDDEV_SAMP(visit_rate_difference) / SQRT(COUNT(*))
        AS visit_difference_standard_error_pct_point,
    100 * AVG(home_store_visit_rate_difference)
        AS mean_home_store_visit_difference_pct_point,
    100 * STDDEV_SAMP(home_store_visit_rate_difference) / SQRT(COUNT(*))
        AS home_store_visit_difference_standard_error_pct_point,
    AVG(sales_value_difference) AS mean_sales_value_difference,
    STDDEV_SAMP(sales_value_difference) / SQRT(COUNT(*))
        AS sales_difference_standard_error,
    AVG(home_store_sales_value_difference)
        AS mean_home_store_sales_value_difference,
    STDDEV_SAMP(home_store_sales_value_difference) / SQRT(COUNT(*))
        AS home_store_sales_difference_standard_error,
    100 * AVG(CASE WHEN visit_rate_difference > 0 THEN 1.0 ELSE 0.0 END)
        AS households_positive_visit_difference_pct,
    100 * AVG(CASE WHEN sales_value_difference > 0 THEN 1.0 ELSE 0.0 END)
        AS households_positive_sales_difference_pct
FROM household_comparison
GROUP BY 1
ORDER BY 1;

CREATE OR REPLACE TABLE mart_visit_gap_exposure_response AS
WITH quartiled AS (
    SELECT
        *,
        NTILE(4) OVER (
            ORDER BY any_feature_exposure, WEEK_NO, household_key
        ) AS exposure_quartile
    FROM work_customer_response_base
    WHERE is_primary_analysis = 1
), segments AS (
    SELECT q.*, s.campaign_segment
    FROM quartiled AS q
    CROSS JOIN LATERAL (
        VALUES
            ('all_weeks'),
            (CASE WHEN q.active_campaign_count > 0
                  THEN 'campaign_active' ELSE 'campaign_inactive' END)
    ) AS s(campaign_segment)
)
SELECT
    campaign_segment,
    visit_gap_band,
    exposure_quartile,
    COUNT(DISTINCT household_key) AS households,
    COUNT(*) AS household_weeks,
    AVG(any_feature_exposure) AS avg_any_feature_exposure,
    AVG(visit) AS visit_rate,
    AVG(sales_value) AS avg_weekly_sales_value
FROM segments
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;

CREATE OR REPLACE TABLE mart_visit_gap_within_response AS
WITH any_feature AS (
    SELECT *
    FROM work_customer_response_centered
    WHERE exposure_type = 'any_feature'
), gap_centered AS (
    SELECT
        *,
        exposure_value - AVG(exposure_value) OVER (
            PARTITION BY household_key, visit_gap_band
        ) AS gap_exposure_deviation
    FROM any_feature
), household_gap AS (
    SELECT
        household_key,
        visit_gap_band,
        COUNT(*) FILTER (WHERE gap_exposure_deviation > 1e-9) AS high_weeks,
        COUNT(*) FILTER (WHERE gap_exposure_deviation < -1e-9) AS low_weeks,
        AVG(exposure_value) FILTER (WHERE gap_exposure_deviation > 1e-9)
            AS high_exposure,
        AVG(exposure_value) FILTER (WHERE gap_exposure_deviation < -1e-9)
            AS low_exposure,
        AVG(visit) FILTER (WHERE gap_exposure_deviation > 1e-9)
            - AVG(visit) FILTER (WHERE gap_exposure_deviation < -1e-9)
            AS visit_rate_difference,
        AVG(home_store_visit) FILTER (WHERE gap_exposure_deviation > 1e-9)
            - AVG(home_store_visit)
                FILTER (WHERE gap_exposure_deviation < -1e-9)
            AS home_store_visit_rate_difference,
        AVG(sales_value) FILTER (WHERE gap_exposure_deviation > 1e-9)
            - AVG(sales_value) FILTER (WHERE gap_exposure_deviation < -1e-9)
            AS sales_value_difference,
        AVG(home_store_sales_value)
            FILTER (WHERE gap_exposure_deviation > 1e-9)
            - AVG(home_store_sales_value)
                FILTER (WHERE gap_exposure_deviation < -1e-9)
            AS home_store_sales_value_difference
    FROM gap_centered
    GROUP BY 1, 2
    HAVING high_weeks > 0 AND low_weeks > 0
)
SELECT
    visit_gap_band,
    COUNT(*) AS comparable_households,
    AVG(high_weeks) AS avg_high_weeks,
    AVG(low_weeks) AS avg_low_weeks,
    AVG(high_exposure) AS avg_high_exposure,
    AVG(low_exposure) AS avg_low_exposure,
    100 * AVG(visit_rate_difference) AS mean_visit_difference_pct_point,
    100 * STDDEV_SAMP(visit_rate_difference) / SQRT(COUNT(*))
        AS visit_difference_standard_error_pct_point,
    100 * AVG(home_store_visit_rate_difference)
        AS mean_home_store_visit_difference_pct_point,
    100 * STDDEV_SAMP(home_store_visit_rate_difference) / SQRT(COUNT(*))
        AS home_store_visit_difference_standard_error_pct_point,
    AVG(sales_value_difference) AS mean_sales_value_difference,
    STDDEV_SAMP(sales_value_difference) / SQRT(COUNT(*))
        AS sales_difference_standard_error,
    AVG(home_store_sales_value_difference)
        AS mean_home_store_sales_value_difference,
    STDDEV_SAMP(home_store_sales_value_difference) / SQRT(COUNT(*))
        AS home_store_sales_difference_standard_error,
    100 * AVG(CASE WHEN visit_rate_difference > 0 THEN 1.0 ELSE 0.0 END)
        AS households_positive_visit_difference_pct,
    100 * AVG(CASE WHEN sales_value_difference > 0 THEN 1.0 ELSE 0.0 END)
        AS households_positive_sales_difference_pct
FROM household_gap
GROUP BY 1
ORDER BY 1;

CREATE OR REPLACE TABLE work_customer_department_week_exposure AS
SELECT
    p.household_key,
    p.DEPARTMENT,
    p.is_preferred_department,
    w.WEEK_NO,
    SUM(p.department_product_weight
        * CASE WHEN COALESCE(r.is_feature_mailer, 0) = 1
                OR COALESCE(r.is_display, 0) = 1
               THEN 1 ELSE 0 END) AS department_any_feature_exposure,
    SUM(p.department_product_weight * COALESCE(r.is_feature_mailer, 0))
        AS department_feature_mailer_exposure,
    SUM(p.department_product_weight * COALESCE(r.is_display, 0))
        AS department_display_exposure,
    SUM(p.department_product_weight
        * CASE WHEN COALESCE(r.is_feature_mailer, 0) = 1
                AND COALESCE(r.is_display, 0) = 1
               THEN 1 ELSE 0 END) AS department_both_exposure,
    COUNT(*) AS eligible_department_products
FROM work_customer_department_product AS p
CROSS JOIN range(27, 102) AS w(WEEK_NO)
LEFT JOIN work_relevant_promotion_clean AS r
  ON p.PRODUCT_ID = r.PRODUCT_ID
 AND p.home_store_id = r.STORE_ID
 AND w.WEEK_NO = r.WEEK_NO
GROUP BY 1, 2, 3, 4;

CREATE OR REPLACE TABLE work_customer_department_response AS
SELECT
    e.*,
    CASE WHEN e.is_preferred_department = 1
         THEN 'preferred_top3' ELSE 'other_purchased' END
        AS department_relation,
    COALESCE(o.department_purchase, 0) AS department_purchase,
    COALESCE(o.department_baskets, 0) AS department_baskets,
    COALESCE(o.department_sales_value, 0.0) AS department_sales_value,
    p.active_campaign_count
FROM work_customer_department_week_exposure AS e
JOIN work_analysis_customer AS c USING (household_key)
JOIN mart_customer_week_panel AS p USING (household_key, WEEK_NO)
LEFT JOIN work_customer_department_week_outcome AS o
  ON e.household_key = o.household_key
 AND e.DEPARTMENT = o.DEPARTMENT
 AND e.WEEK_NO = o.WEEK_NO
WHERE c.is_primary_analysis = 1;

CREATE OR REPLACE TABLE mart_department_response AS
SELECT
    department_relation,
    CASE WHEN department_any_feature_exposure > 0
         THEN 'exposed' ELSE 'not_exposed' END AS exposure_state,
    COUNT(DISTINCT household_key) AS households,
    COUNT(DISTINCT (household_key, DEPARTMENT)) AS household_departments,
    COUNT(*) AS household_department_weeks,
    AVG(department_any_feature_exposure) AS avg_any_feature_exposure,
    AVG(department_feature_mailer_exposure) AS avg_feature_mailer_exposure,
    AVG(department_display_exposure) AS avg_display_exposure,
    AVG(department_both_exposure) AS avg_both_exposure,
    AVG(department_purchase) AS department_purchase_rate,
    AVG(department_sales_value) AS avg_department_sales_value,
    AVG(CASE WHEN active_campaign_count > 0 THEN 1.0 ELSE 0.0 END)
        AS active_campaign_week_rate
FROM work_customer_department_response
GROUP BY 1, 2
ORDER BY 1, 2;

CREATE OR REPLACE TABLE mart_department_within_response AS
WITH centered AS (
    SELECT
        *,
        department_any_feature_exposure - AVG(department_any_feature_exposure)
            OVER (PARTITION BY household_key, DEPARTMENT)
            AS exposure_deviation
    FROM work_customer_department_response
), household_department AS (
    SELECT
        household_key,
        DEPARTMENT,
        department_relation,
        COUNT(*) FILTER (WHERE exposure_deviation > 1e-9) AS high_weeks,
        COUNT(*) FILTER (WHERE exposure_deviation < -1e-9) AS low_weeks,
        AVG(department_any_feature_exposure)
            FILTER (WHERE exposure_deviation > 1e-9) AS high_exposure,
        AVG(department_any_feature_exposure)
            FILTER (WHERE exposure_deviation < -1e-9) AS low_exposure,
        AVG(department_purchase) FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(department_purchase)
                FILTER (WHERE exposure_deviation < -1e-9)
            AS purchase_rate_difference,
        AVG(department_sales_value) FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(department_sales_value)
                FILTER (WHERE exposure_deviation < -1e-9)
            AS sales_value_difference
    FROM centered
    GROUP BY 1, 2, 3
    HAVING high_weeks > 0 AND low_weeks > 0
)
SELECT
    department_relation,
    COUNT(DISTINCT household_key) AS comparable_households,
    COUNT(*) AS comparable_household_departments,
    AVG(high_exposure) AS avg_high_exposure,
    AVG(low_exposure) AS avg_low_exposure,
    100 * AVG(purchase_rate_difference) AS mean_purchase_difference_pct_point,
    100 * STDDEV_SAMP(purchase_rate_difference) / SQRT(COUNT(*))
        AS purchase_difference_standard_error_pct_point,
    AVG(sales_value_difference) AS mean_sales_value_difference,
    STDDEV_SAMP(sales_value_difference) / SQRT(COUNT(*))
        AS sales_difference_standard_error,
    100 * AVG(CASE WHEN purchase_rate_difference > 0 THEN 1.0 ELSE 0.0 END)
        AS pairs_positive_purchase_difference_pct,
    100 * AVG(CASE WHEN sales_value_difference > 0 THEN 1.0 ELSE 0.0 END)
        AS pairs_positive_sales_difference_pct
FROM household_department
GROUP BY 1
ORDER BY 1;

CREATE OR REPLACE TABLE mart_department_detail AS
WITH centered AS (
    SELECT
        *,
        department_any_feature_exposure - AVG(department_any_feature_exposure)
            OVER (PARTITION BY household_key, DEPARTMENT)
            AS exposure_deviation
    FROM work_customer_department_response
), household_department AS (
    SELECT
        household_key,
        DEPARTMENT,
        department_relation,
        COUNT(*) FILTER (WHERE exposure_deviation > 1e-9) AS high_weeks,
        COUNT(*) FILTER (WHERE exposure_deviation < -1e-9) AS low_weeks,
        AVG(department_purchase) FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(department_purchase)
                FILTER (WHERE exposure_deviation < -1e-9)
            AS purchase_rate_difference,
        AVG(department_sales_value) FILTER (WHERE exposure_deviation > 1e-9)
            - AVG(department_sales_value)
                FILTER (WHERE exposure_deviation < -1e-9)
            AS sales_value_difference
    FROM centered
    GROUP BY 1, 2, 3
    HAVING high_weeks > 0 AND low_weeks > 0
)
SELECT
    DEPARTMENT,
    department_relation,
    COUNT(*) AS comparable_household_departments,
    COUNT(DISTINCT household_key) AS comparable_households,
    100 * AVG(purchase_rate_difference) AS mean_purchase_difference_pct_point,
    100 * STDDEV_SAMP(purchase_rate_difference) / SQRT(COUNT(*))
        AS purchase_difference_standard_error_pct_point,
    AVG(sales_value_difference) AS mean_sales_value_difference,
    STDDEV_SAMP(sales_value_difference) / SQRT(COUNT(*))
        AS sales_difference_standard_error,
    100 * AVG(CASE WHEN purchase_rate_difference > 0 THEN 1.0 ELSE 0.0 END)
        AS pairs_positive_purchase_difference_pct,
    100 * AVG(CASE WHEN sales_value_difference > 0 THEN 1.0 ELSE 0.0 END)
        AS pairs_positive_sales_difference_pct
FROM household_department
GROUP BY 1, 2
HAVING COUNT(DISTINCT household_key) >= 30
ORDER BY comparable_households DESC, DEPARTMENT, department_relation;
