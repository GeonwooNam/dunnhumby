-- 목적: 1~26주 고객 특성, 고정 홈스토어와 사전 표본 플래그를 만든다.
-- 입력: 00 단계 작업 테이블, source.product, source.causal_data
-- 출력: work_baseline_customer, audit_customer_sample_flow 등

CREATE OR REPLACE TABLE work_causal_store AS
SELECT DISTINCT STORE_ID
FROM source.causal_data;

CREATE OR REPLACE TABLE work_customer_first_observed AS
SELECT
    household_key,
    MIN(WEEK_NO) AS first_observed_week,
    MAX(WEEK_NO) AS last_observed_week
FROM source.transaction_data
GROUP BY 1;

CREATE OR REPLACE TABLE work_baseline_visit_gap AS
WITH visit_weeks AS (
    SELECT DISTINCT household_key, WEEK_NO
    FROM work_customer_basket
    WHERE WEEK_NO BETWEEN 1 AND 26
), gaps AS (
    SELECT
        household_key,
        WEEK_NO - LAG(WEEK_NO) OVER (
            PARTITION BY household_key ORDER BY WEEK_NO
        ) AS gap_weeks
    FROM visit_weeks
)
SELECT
    household_key,
    MEDIAN(gap_weeks) FILTER (WHERE gap_weeks IS NOT NULL)
        AS baseline_median_gap,
    COUNT(gap_weeks) FILTER (WHERE gap_weeks IS NOT NULL)
        AS baseline_gap_count
FROM gaps
GROUP BY 1;

CREATE OR REPLACE TABLE work_home_store AS
WITH store_baskets AS (
    SELECT
        household_key,
        STORE_ID,
        COUNT(*) AS store_baskets,
        SUM(basket_sales_value) AS store_sales_value
    FROM work_customer_basket
    WHERE WEEK_NO BETWEEN 1 AND 26
    GROUP BY 1, 2
), ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY household_key
            ORDER BY store_baskets DESC, store_sales_value DESC, STORE_ID
        ) AS store_rank,
        SUM(store_baskets) OVER (PARTITION BY household_key)
            AS total_baseline_baskets
    FROM store_baskets
)
SELECT
    household_key,
    STORE_ID AS home_store_id,
    store_baskets AS home_store_baskets,
    total_baseline_baskets,
    store_sales_value AS home_store_sales_value,
    store_baskets::DOUBLE / NULLIF(total_baseline_baskets, 0)
        AS baseline_home_store_share
FROM ranked
WHERE store_rank = 1;

CREATE OR REPLACE TABLE work_baseline_customer AS
WITH basket_summary AS (
    SELECT
        household_key,
        COUNT(*) AS baseline_baskets,
        COUNT(DISTINCT WEEK_NO) AS n_baseline_purchase_weeks,
        COUNT(DISTINCT STORE_ID) AS baseline_stores,
        SUM(basket_sales_value) AS baseline_sales_value,
        AVG(basket_sales_value) AS baseline_avg_basket_value
    FROM work_customer_basket
    WHERE WEEK_NO BETWEEN 1 AND 26
    GROUP BY 1
), product_summary AS (
    SELECT
        t.household_key,
        COUNT(DISTINCT t.PRODUCT_ID) AS baseline_products,
        COUNT(DISTINCT p.DEPARTMENT) AS baseline_departments,
        COUNT(DISTINCT p.COMMODITY_DESC) AS baseline_commodities
    FROM work_customer_transaction AS t
    LEFT JOIN source.product AS p USING (PRODUCT_ID)
    WHERE t.WEEK_NO BETWEEN 1 AND 26
    GROUP BY 1
), outcome_home_share AS (
    SELECT
        h.household_key,
        COUNT(b.BASKET_ID) FILTER (WHERE b.STORE_ID = h.home_store_id)::DOUBLE
            / NULLIF(COUNT(b.BASKET_ID), 0) AS outcome_home_store_share,
        COUNT(b.BASKET_ID) AS outcome_baskets
    FROM work_home_store AS h
    LEFT JOIN work_customer_basket AS b
      ON h.household_key = b.household_key
     AND b.WEEK_NO BETWEEN 27 AND 101
    GROUP BY 1
)
SELECT
    b.household_key,
    f.first_observed_week,
    f.last_observed_week,
    b.baseline_baskets,
    b.n_baseline_purchase_weeks,
    GREATEST(27 - f.first_observed_week, 1)
        AS baseline_observable_weeks,
    b.n_baseline_purchase_weeks::DOUBLE
        / GREATEST(27 - f.first_observed_week, 1)
        AS baseline_weekly_visit_rate,
    b.baseline_stores,
    b.baseline_sales_value,
    b.baseline_avg_basket_value,
    p.baseline_products,
    p.baseline_departments,
    p.baseline_commodities,
    g.baseline_median_gap,
    g.baseline_gap_count,
    h.home_store_id,
    h.home_store_baskets,
    h.baseline_home_store_share,
    o.outcome_home_store_share,
    o.outcome_baskets,
    CASE WHEN cs.STORE_ID IS NOT NULL THEN 1 ELSE 0 END
        AS home_store_in_causal,
    CASE
        WHEN b.baseline_baskets >= 5
         AND cs.STORE_ID IS NOT NULL THEN 1 ELSE 0
    END AS is_candidate,
    CASE
        WHEN b.baseline_baskets >= 5
         AND cs.STORE_ID IS NOT NULL
         AND b.n_baseline_purchase_weeks >= 8
         AND h.baseline_home_store_share >= 0.50
        THEN 1 ELSE 0
    END AS is_primary_preference_pending,
    CASE
        WHEN b.baseline_baskets >= 5
         AND cs.STORE_ID IS NOT NULL
         AND b.n_baseline_purchase_weeks >= 8
         AND h.baseline_home_store_share >= 0.70
        THEN 1 ELSE 0
    END AS is_home70_preference_pending
FROM basket_summary AS b
JOIN work_customer_first_observed AS f USING (household_key)
JOIN work_home_store AS h USING (household_key)
LEFT JOIN product_summary AS p USING (household_key)
LEFT JOIN work_baseline_visit_gap AS g USING (household_key)
LEFT JOIN outcome_home_share AS o USING (household_key)
LEFT JOIN work_causal_store AS cs ON h.home_store_id = cs.STORE_ID;

CREATE OR REPLACE TABLE audit_customer_sample_flow AS
SELECT 1 AS step_no, 'all_panel_households' AS step,
       COUNT(DISTINCT household_key) AS households
FROM source.transaction_data
UNION ALL
SELECT 2, 'baseline_purchase_observed', COUNT(*)
FROM work_baseline_customer
UNION ALL
SELECT 3, 'baseline_baskets_5plus', COUNT(*)
FROM work_baseline_customer WHERE baseline_baskets >= 5
UNION ALL
SELECT 4, 'candidate_home_store_in_causal', COUNT(*)
FROM work_baseline_customer WHERE is_candidate = 1
UNION ALL
SELECT 5, 'candidate_baseline_weeks_8plus', COUNT(*)
FROM work_baseline_customer
WHERE is_candidate = 1 AND n_baseline_purchase_weeks >= 8
UNION ALL
SELECT 6, 'primary_before_preference', COUNT(*)
FROM work_baseline_customer WHERE is_primary_preference_pending = 1
UNION ALL
SELECT 90, 'sensitivity_home70_before_preference', COUNT(*)
FROM work_baseline_customer WHERE is_home70_preference_pending = 1;

CREATE OR REPLACE TABLE audit_customer_candidate_definition AS
WITH raw_baseline_basket AS (
    SELECT
        household_key,
        BASKET_ID,
        MIN(STORE_ID) AS STORE_ID,
        SUM(SALES_VALUE) AS basket_sales_value
    FROM source.transaction_data
    WHERE WEEK_NO BETWEEN 1 AND 26
    GROUP BY 1, 2
), raw_store AS (
    SELECT
        household_key,
        STORE_ID,
        COUNT(*) AS store_baskets,
        SUM(basket_sales_value) AS store_sales,
        ROW_NUMBER() OVER (
            PARTITION BY household_key
            ORDER BY COUNT(*) DESC, SUM(basket_sales_value) DESC, STORE_ID
        ) AS store_rank
    FROM raw_baseline_basket
    GROUP BY 1, 2
), raw_customer AS (
    SELECT household_key, COUNT(*) AS baseline_baskets
    FROM raw_baseline_basket
    GROUP BY 1
)
SELECT
    'raw_all_transaction_rows' AS candidate_definition,
    COUNT(*) AS households
FROM raw_customer AS c
JOIN raw_store AS h USING (household_key)
JOIN work_causal_store AS s ON h.STORE_ID = s.STORE_ID
WHERE h.store_rank = 1 AND c.baseline_baskets >= 5
UNION ALL
SELECT
    'exclude_zero_quantity_zero_sales_product_rows',
    COUNT(*)
FROM work_baseline_customer
WHERE is_candidate = 1;

CREATE OR REPLACE TABLE audit_customer_baseline_weeks AS
SELECT
    CASE
        WHEN n_baseline_purchase_weeks <= 4 THEN '01_1_4'
        WHEN n_baseline_purchase_weeks <= 7 THEN '02_5_7'
        WHEN n_baseline_purchase_weeks <= 13 THEN '03_8_13'
        ELSE '04_14_26'
    END AS baseline_week_band,
    COUNT(*) AS households,
    AVG(baseline_baskets) AS avg_baseline_baskets,
    AVG(baseline_home_store_share) AS avg_home_store_share
FROM work_baseline_customer
WHERE is_candidate = 1
GROUP BY 1
ORDER BY 1;

CREATE OR REPLACE TABLE audit_customer_home_store_share AS
WITH long_share AS (
    SELECT household_key, 'baseline' AS period,
           baseline_home_store_share AS home_store_share
    FROM work_baseline_customer WHERE is_candidate = 1
    UNION ALL
    SELECT household_key, 'outcome', outcome_home_store_share
    FROM work_baseline_customer WHERE is_candidate = 1
)
SELECT
    period,
    COUNT(*) AS households,
    AVG(home_store_share) AS avg_home_store_share,
    MEDIAN(home_store_share) AS median_home_store_share,
    QUANTILE_CONT(home_store_share, 0.25) AS p25,
    QUANTILE_CONT(home_store_share, 0.75) AS p75,
    AVG(CASE WHEN home_store_share < 0.50 THEN 1.0 ELSE 0.0 END)
        AS share_below_50_rate
FROM long_share
GROUP BY 1
ORDER BY 1;
