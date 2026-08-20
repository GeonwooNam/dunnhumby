-- 목적: 27~101주 고객의 방문·수취액, 직전 방문 공백과 캠페인 중첩을 만든다.
-- 입력: 00~03 단계 고객, 거래, 달력, 캠페인 테이블
-- 출력: mart_customer_week_panel, 부문 결과와 상태·캠페인 감사표

CREATE OR REPLACE TABLE work_campaign_customer_week AS
SELECT
    c.household_key,
    w.WEEK_NO,
    COUNT(DISTINCT c.CAMPAIGN) AS active_campaign_count,
    COUNT(DISTINCT c.DESCRIPTION) AS active_campaign_type_count,
    MAX(CASE WHEN c.DESCRIPTION = 'TypeA' THEN 1 ELSE 0 END)
        AS active_type_a,
    MAX(CASE WHEN c.DESCRIPTION = 'TypeB' THEN 1 ELSE 0 END)
        AS active_type_b,
    MAX(CASE WHEN c.DESCRIPTION = 'TypeC' THEN 1 ELSE 0 END)
        AS active_type_c
FROM source.campaign_table AS c
JOIN source.campaign_desc AS d
  ON c.CAMPAIGN = d.CAMPAIGN
 AND c.DESCRIPTION = d.DESCRIPTION
JOIN work_week_calendar AS w
  ON d.START_DAY <= w.week_end_day
 AND d.END_DAY >= w.week_start_day
WHERE w.WEEK_NO BETWEEN 27 AND 101
GROUP BY 1, 2;

CREATE OR REPLACE TABLE work_campaign_recipient AS
SELECT
    household_key,
    COUNT(DISTINCT CAMPAIGN) AS assigned_campaigns,
    COUNT(DISTINCT DESCRIPTION) AS assigned_campaign_types,
    MAX(CASE WHEN DESCRIPTION = 'TypeA' THEN 1 ELSE 0 END)
        AS ever_type_a,
    MAX(CASE WHEN DESCRIPTION = 'TypeB' THEN 1 ELSE 0 END)
        AS ever_type_b,
    MAX(CASE WHEN DESCRIPTION = 'TypeC' THEN 1 ELSE 0 END)
        AS ever_type_c
FROM source.campaign_table
GROUP BY 1;

CREATE OR REPLACE TABLE work_customer_week_outcome AS
WITH basket_week AS (
    SELECT
        b.household_key,
        b.WEEK_NO,
        COUNT(*) AS baskets,
        COUNT(*) FILTER (WHERE b.STORE_ID = c.home_store_id)
            AS home_store_baskets,
        SUM(b.basket_sales_value) AS sales_value,
        SUM(b.basket_sales_value)
            FILTER (WHERE b.STORE_ID = c.home_store_id)
            AS home_store_sales_value
    FROM work_customer_basket AS b
    JOIN work_analysis_customer AS c USING (household_key)
    WHERE b.WEEK_NO BETWEEN 1 AND 101
      AND c.is_candidate_analysis = 1
    GROUP BY 1, 2
), department_week AS (
    SELECT
        t.household_key,
        t.WEEK_NO,
        COUNT(DISTINCT p.DEPARTMENT) AS departments_purchased
    FROM work_customer_transaction AS t
    JOIN work_analysis_customer AS c USING (household_key)
    LEFT JOIN source.product AS p USING (PRODUCT_ID)
    WHERE t.WEEK_NO BETWEEN 1 AND 101
      AND c.is_candidate_analysis = 1
    GROUP BY 1, 2
)
SELECT
    b.household_key,
    b.WEEK_NO,
    1 AS visit,
    CASE WHEN b.home_store_baskets > 0 THEN 1 ELSE 0 END
        AS home_store_visit,
    b.baskets,
    b.home_store_baskets,
    b.sales_value,
    COALESCE(b.home_store_sales_value, 0.0) AS home_store_sales_value,
    COALESCE(d.departments_purchased, 0) AS departments_purchased
FROM basket_week AS b
LEFT JOIN department_week AS d USING (household_key, WEEK_NO);

CREATE OR REPLACE TABLE work_customer_week_all AS
WITH grid AS (
    SELECT
        c.household_key,
        w.WEEK_NO,
        c.home_store_id,
        c.baseline_weekly_visit_rate,
        c.baseline_median_gap,
        c.baseline_gap_count,
        c.first_observed_week,
        c.n_baseline_purchase_weeks,
        c.baseline_home_store_share,
        c.outcome_home_store_share,
        c.n_eligible_products,
        c.excluded_weight_share,
        c.is_candidate_analysis,
        c.is_primary_analysis,
        c.is_primary_eligible1_analysis,
        c.is_primary_all_weeks_analysis,
        c.is_primary_no_history_filter_analysis,
        c.is_home70_analysis,
        COALESCE(o.visit, 0) AS visit,
        COALESCE(o.home_store_visit, 0) AS home_store_visit,
        COALESCE(o.baskets, 0) AS baskets,
        COALESCE(o.home_store_baskets, 0) AS home_store_baskets,
        COALESCE(o.sales_value, 0.0) AS sales_value,
        COALESCE(o.home_store_sales_value, 0.0) AS home_store_sales_value,
        COALESCE(o.departments_purchased, 0) AS departments_purchased
    FROM work_analysis_customer AS c
    CROSS JOIN range(1, 102) AS w(WEEK_NO)
    LEFT JOIN work_customer_week_outcome AS o
      ON c.household_key = o.household_key
     AND w.WEEK_NO = o.WEEK_NO
    WHERE c.is_candidate_analysis = 1
), history AS (
    SELECT
        *,
        MAX(CASE WHEN visit = 1 THEN WEEK_NO END) OVER (
            PARTITION BY household_key ORDER BY WEEK_NO
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS last_visit_week,
        SUM(visit) OVER (
            PARTITION BY household_key ORDER BY WEEK_NO
            ROWS BETWEEN 8 PRECEDING AND 1 PRECEDING
        ) AS visits_previous_8_weeks
    FROM grid
)
SELECT
    *,
    WEEK_NO - last_visit_week AS weeks_since_last_visit,
    visits_previous_8_weeks / 8.0 AS recent_8w_visit_rate,
    CASE
        WHEN baseline_weekly_visit_rate > 0 THEN
            (baseline_weekly_visit_rate - visits_previous_8_weeks / 8.0)
            / baseline_weekly_visit_rate
        ELSE NULL
    END AS recent_8w_frequency_decline,
    CASE
        WHEN WEEK_NO - last_visit_week = 1 THEN '01_1_week'
        WHEN WEEK_NO - last_visit_week = 2 THEN '02_2_weeks'
        WHEN WEEK_NO - last_visit_week BETWEEN 3 AND 4 THEN '03_3_4_weeks'
        WHEN WEEK_NO - last_visit_week >= 5 THEN '04_5plus_weeks'
        ELSE '05_no_prior_visit'
    END AS visit_gap_band,
    CASE
        WHEN WEEK_NO - last_visit_week
             >= GREATEST(CEIL(COALESCE(baseline_median_gap, 2) * 1.5), 3)
        THEN 1 ELSE 0
    END AS conservative_risk_flag
FROM history;

CREATE OR REPLACE TABLE mart_customer_week_panel AS
SELECT
    a.*,
    COALESCE(c.active_campaign_count, 0) AS active_campaign_count,
    COALESCE(c.active_campaign_type_count, 0) AS active_campaign_type_count,
    COALESCE(c.active_type_a, 0) AS active_type_a,
    COALESCE(c.active_type_b, 0) AS active_type_b,
    COALESCE(c.active_type_c, 0) AS active_type_c,
    COALESCE(r.assigned_campaigns, 0) AS assigned_campaigns,
    CASE WHEN COALESCE(r.assigned_campaigns, 0) > 0 THEN 1 ELSE 0 END
        AS ever_campaign_recipient
FROM work_customer_week_all AS a
LEFT JOIN work_campaign_customer_week AS c
  ON a.household_key = c.household_key
 AND a.WEEK_NO = c.WEEK_NO
LEFT JOIN work_campaign_recipient AS r
  ON a.household_key = r.household_key
WHERE a.WEEK_NO BETWEEN 27 AND 101;

CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_week_panel
ON mart_customer_week_panel (household_key, WEEK_NO);

CREATE OR REPLACE TABLE work_customer_department_week_outcome AS
SELECT
    t.household_key,
    p.DEPARTMENT,
    t.WEEK_NO,
    1 AS department_purchase,
    COUNT(DISTINCT t.BASKET_ID) AS department_baskets,
    SUM(t.SALES_VALUE) AS department_sales_value
FROM work_customer_transaction AS t
JOIN work_analysis_customer AS c USING (household_key)
JOIN source.product AS p USING (PRODUCT_ID)
WHERE t.WEEK_NO BETWEEN 27 AND 101
  AND c.is_candidate_analysis = 1
  AND p.DEPARTMENT IS NOT NULL
  AND TRIM(p.DEPARTMENT) <> ''
GROUP BY 1, 2, 3;

CREATE OR REPLACE TABLE audit_customer_state_distribution AS
SELECT
    visit_gap_band,
    COUNT(DISTINCT household_key) AS households,
    COUNT(*) AS household_weeks,
    AVG(visit) AS visit_rate,
    AVG(sales_value) AS avg_sales_value,
    AVG(recent_8w_frequency_decline) AS avg_frequency_decline,
    AVG(conservative_risk_flag) AS conservative_risk_rate
FROM mart_customer_week_panel
WHERE is_primary_analysis = 1
GROUP BY 1
ORDER BY 1;

CREATE OR REPLACE TABLE audit_customer_campaign_overlap AS
SELECT
    CASE
        WHEN active_campaign_count = 0 THEN '0_none'
        WHEN active_campaign_count = 1 THEN '1_one'
        ELSE '2_plus'
    END AS active_campaign_band,
    COUNT(DISTINCT household_key) AS households,
    COUNT(*) AS household_weeks,
    AVG(visit) AS visit_rate,
    AVG(sales_value) AS avg_sales_value
FROM mart_customer_week_panel
WHERE is_primary_analysis = 1
GROUP BY 1
ORDER BY 1;

CREATE OR REPLACE TABLE audit_customer_panel_outcome AS
SELECT
    COUNT(DISTINCT household_key) AS households,
    COUNT(*) AS household_weeks,
    AVG(visit) AS visit_rate,
    AVG(home_store_visit) AS home_store_visit_rate,
    AVG(baskets) AS avg_baskets,
    AVG(sales_value) AS avg_weekly_sales_value,
    AVG(sales_value) FILTER (WHERE visit = 1) AS avg_sales_per_visit_week,
    AVG(CASE WHEN active_campaign_count > 0 THEN 1.0 ELSE 0.0 END)
        AS active_campaign_week_rate,
    AVG(ever_campaign_recipient) AS campaign_recipient_household_week_rate
FROM mart_customer_week_panel
WHERE is_primary_analysis = 1;
