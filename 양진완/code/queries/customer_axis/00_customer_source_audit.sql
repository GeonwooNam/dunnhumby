-- 목적: 고객축 실행 전에 원본 주차, 패널 진입, 프로모션 코드와 캠페인 구조를 감사한다.
-- 입력: source.transaction_data, source.causal_data, source.campaign_desc, source.campaign_table
-- 출력: audit_customer_* 테이블과 공통 주차·거래 작업 테이블

CREATE OR REPLACE TABLE work_week_calendar AS
SELECT
    WEEK_NO,
    MIN(DAY) AS week_start_day,
    MAX(DAY) AS week_end_day,
    COUNT(DISTINCT DAY) AS observed_days
FROM source.transaction_data
GROUP BY 1;

CREATE OR REPLACE TABLE work_customer_transaction AS
SELECT
    household_key,
    BASKET_ID,
    DAY,
    PRODUCT_ID,
    QUANTITY,
    SALES_VALUE,
    STORE_ID,
    RETAIL_DISC,
    WEEK_NO,
    COUPON_DISC,
    COUPON_MATCH_DISC
FROM source.transaction_data
WHERE WEEK_NO BETWEEN 1 AND 101
  AND NOT (
      COALESCE(QUANTITY, 0) = 0
      AND COALESCE(SALES_VALUE, 0) = 0
  );

CREATE OR REPLACE TABLE work_customer_basket AS
SELECT
    household_key,
    BASKET_ID,
    MIN(DAY) AS basket_day,
    MIN(WEEK_NO) AS WEEK_NO,
    MIN(STORE_ID) AS STORE_ID,
    SUM(SALES_VALUE) AS basket_sales_value,
    COUNT(DISTINCT PRODUCT_ID) AS distinct_products
FROM work_customer_transaction
GROUP BY 1, 2;

CREATE OR REPLACE TABLE audit_customer_source_overview AS
SELECT
    'transaction_data' AS table_name,
    COUNT(*) AS row_count,
    COUNT(DISTINCT household_key) AS household_count,
    COUNT(DISTINCT PRODUCT_ID) AS product_count,
    COUNT(DISTINCT STORE_ID) AS store_count,
    MIN(WEEK_NO) AS min_week,
    MAX(WEEK_NO) AS max_week
FROM source.transaction_data
UNION ALL
SELECT
    'causal_data',
    COUNT(*),
    NULL,
    COUNT(DISTINCT PRODUCT_ID),
    COUNT(DISTINCT STORE_ID),
    MIN(WEEK_NO),
    MAX(WEEK_NO)
FROM source.causal_data
UNION ALL
SELECT
    'campaign_table',
    COUNT(*),
    COUNT(DISTINCT household_key),
    NULL,
    NULL,
    NULL,
    NULL
FROM source.campaign_table;

CREATE OR REPLACE TABLE audit_customer_week_calendar AS
SELECT
    WEEK_NO,
    week_start_day,
    week_end_day,
    observed_days,
    CASE
        WHEN WEEK_NO = 102 AND observed_days < 7 THEN 'exclude_partial_week'
        WHEN WEEK_NO BETWEEN 1 AND 26 THEN 'baseline'
        WHEN WEEK_NO BETWEEN 27 AND 101 THEN 'outcome'
        ELSE 'outside_analysis'
    END AS analysis_period
FROM work_week_calendar
ORDER BY WEEK_NO;

CREATE OR REPLACE TABLE audit_customer_entry_week AS
WITH first_purchase AS (
    SELECT household_key, MIN(WEEK_NO) AS first_observed_week
    FROM source.transaction_data
    GROUP BY 1
)
SELECT
    CASE
        WHEN first_observed_week = 1 THEN '01_week_1'
        WHEN first_observed_week BETWEEN 2 AND 4 THEN '02_weeks_2_4'
        WHEN first_observed_week BETWEEN 5 AND 13 THEN '03_weeks_5_13'
        WHEN first_observed_week BETWEEN 14 AND 26 THEN '04_weeks_14_26'
        ELSE '05_week_27_plus'
    END AS entry_band,
    COUNT(*) AS households
FROM first_purchase
GROUP BY 1
ORDER BY 1;

CREATE OR REPLACE TABLE audit_customer_promo_codes AS
SELECT
    'mailer' AS code_type,
    mailer AS code,
    COUNT(*) AS row_count,
    COUNT(DISTINCT (PRODUCT_ID, STORE_ID, WEEK_NO)) AS key_count
FROM source.causal_data
GROUP BY 1, 2
UNION ALL
SELECT
    'display',
    display,
    COUNT(*),
    COUNT(DISTINCT (PRODUCT_ID, STORE_ID, WEEK_NO))
FROM source.causal_data
GROUP BY 1, 2;

CREATE OR REPLACE TABLE audit_customer_promo_key_quality AS
WITH key_quality AS (
    SELECT
        PRODUCT_ID,
        STORE_ID,
        WEEK_NO,
        COUNT(*) AS source_rows,
        COUNT(DISTINCT mailer) AS mailer_codes,
        COUNT(DISTINCT display) AS display_codes
    FROM source.causal_data
    GROUP BY 1, 2, 3
)
SELECT
    COUNT(*) AS distinct_keys,
    COUNT(*) FILTER (WHERE source_rows > 1) AS duplicated_keys,
    COUNT(*) FILTER (
        WHERE mailer_codes > 1 OR display_codes > 1
    ) AS conflicting_keys,
    MAX(source_rows) AS max_rows_per_key
FROM key_quality;

CREATE OR REPLACE TABLE audit_customer_campaign_overview AS
WITH campaign_households AS (
    SELECT
        c.DESCRIPTION,
        COUNT(DISTINCT c.CAMPAIGN) AS campaigns,
        COUNT(DISTINCT c.household_key) AS households,
        COUNT(*) AS assignments
    FROM source.campaign_table AS c
    GROUP BY 1
)
SELECT
    d.DESCRIPTION AS campaign_type,
    COUNT(DISTINCT d.CAMPAIGN) AS campaigns,
    MIN(d.START_DAY) AS first_start_day,
    MAX(d.END_DAY) AS last_end_day,
    h.households,
    h.assignments
FROM source.campaign_desc AS d
LEFT JOIN campaign_households AS h USING (DESCRIPTION)
GROUP BY 1, 5, 6
ORDER BY 1;

CREATE OR REPLACE TABLE audit_customer_transaction_quality AS
SELECT
    COUNT(*) AS raw_rows,
    COUNT(*) FILTER (
        WHERE COALESCE(QUANTITY, 0) = 0
          AND COALESCE(SALES_VALUE, 0) = 0
    ) AS zero_quantity_zero_sales_rows,
    COUNT(*) FILTER (WHERE WEEK_NO = 102) AS partial_week_rows,
    COUNT(DISTINCT BASKET_ID) AS baskets,
    COUNT(DISTINCT household_key) AS households
FROM source.transaction_data;
