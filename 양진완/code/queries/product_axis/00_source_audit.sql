-- 목적: 상품 축 분석 전에 원본 범위, 키 품질, 프로모션 코드와 패널 크기를 점검한다.
-- 입력: source.transaction_data, source.product, source.causal_data
-- 출력: audit_source_overview, audit_promo_codes, audit_key_quality,
--       audit_store_coverage, audit_active_panel_size, audit_store_variation,
--       audit_panel_structure, audit_store_week_traffic

CREATE OR REPLACE TABLE audit_source_overview AS
SELECT
    'transaction_data' AS table_name,
    COUNT(*) AS row_count,
    COUNT(DISTINCT PRODUCT_ID) AS product_count,
    COUNT(DISTINCT STORE_ID) AS store_count,
    MIN(WEEK_NO) AS min_week,
    MAX(WEEK_NO) AS max_week
FROM source.transaction_data
UNION ALL
SELECT
    'causal_data',
    COUNT(*),
    COUNT(DISTINCT PRODUCT_ID),
    COUNT(DISTINCT STORE_ID),
    MIN(WEEK_NO),
    MAX(WEEK_NO)
FROM source.causal_data
UNION ALL
SELECT
    'product',
    COUNT(*),
    COUNT(DISTINCT PRODUCT_ID),
    NULL,
    NULL,
    NULL
FROM source.product;

CREATE OR REPLACE TABLE audit_promo_codes AS
SELECT
    'mailer' AS promo_type,
    COALESCE(mailer, '<NULL>') AS promo_code,
    COUNT(*) AS row_count
FROM source.causal_data
GROUP BY 1, 2
UNION ALL
SELECT
    'display',
    COALESCE(display, '<NULL>'),
    COUNT(*)
FROM source.causal_data
GROUP BY 1, 2;

CREATE OR REPLACE TABLE audit_key_quality AS
WITH key_counts AS (
    SELECT
        PRODUCT_ID,
        STORE_ID,
        WEEK_NO,
        COUNT(*) AS raw_rows,
        COUNT(DISTINCT mailer) AS n_raw_mailer_codes,
        COUNT(DISTINCT display) AS n_raw_display_codes,
        MAX(CASE
            WHEN mailer = '0' AND display IN ('0', 'A') THEN 1 ELSE 0
        END) AS has_explicit_none_row
    FROM source.causal_data
    GROUP BY 1, 2, 3
)
SELECT
    COUNT(*) AS distinct_keys,
    SUM(raw_rows) AS raw_rows,
    SUM(raw_rows - 1) AS duplicate_rows,
    COUNT(*) FILTER (WHERE raw_rows > 1) AS duplicate_keys,
    COUNT(*) FILTER (
        WHERE n_raw_mailer_codes > 1 OR n_raw_display_codes > 1
    ) AS conflicting_code_keys,
    COUNT(*) FILTER (
        WHERE has_explicit_none_row = 1
          AND n_raw_mailer_codes = 1
          AND n_raw_display_codes = 1
    ) AS explicit_no_promotion_keys
FROM key_counts;

CREATE OR REPLACE TABLE audit_store_coverage AS
WITH causal_stores AS (
    SELECT DISTINCT STORE_ID
    FROM source.causal_data
),
transaction_scope AS (
    SELECT *
    FROM source.transaction_data
    WHERE WEEK_NO BETWEEN 9 AND 101
)
SELECT
    COUNT(*) AS transaction_rows,
    COUNT(*) FILTER (WHERE c.STORE_ID IS NOT NULL) AS covered_rows,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE c.STORE_ID IS NOT NULL) / COUNT(*),
        2
    ) AS covered_row_pct,
    SUM(t.SALES_VALUE) AS transaction_sales,
    SUM(t.SALES_VALUE) FILTER (WHERE c.STORE_ID IS NOT NULL) AS covered_sales,
    ROUND(
        100.0 * SUM(t.SALES_VALUE) FILTER (WHERE c.STORE_ID IS NOT NULL)
        / NULLIF(SUM(t.SALES_VALUE), 0),
        2
    ) AS covered_sales_pct
FROM transaction_scope AS t
LEFT JOIN causal_stores AS c USING (STORE_ID);

CREATE OR REPLACE TABLE audit_active_panel_size AS
WITH causal_stores AS (
    SELECT DISTINCT STORE_ID
    FROM source.causal_data
),
active_pairs AS (
    SELECT
        t.PRODUCT_ID,
        t.STORE_ID,
        MIN(t.WEEK_NO) AS first_week,
        MAX(t.WEEK_NO) AS last_week,
        COUNT(DISTINCT t.WEEK_NO) AS sold_weeks
    FROM source.transaction_data AS t
    INNER JOIN causal_stores AS s USING (STORE_ID)
    WHERE t.WEEK_NO BETWEEN 9 AND 101
      AND (t.QUANTITY > 0 OR t.SALES_VALUE > 0)
    GROUP BY 1, 2
)
SELECT
    threshold AS min_sold_weeks,
    COUNT(*) FILTER (WHERE sold_weeks >= threshold) AS product_store_pairs,
    SUM(last_week - first_week + 1)
        FILTER (WHERE sold_weeks >= threshold) AS estimated_panel_rows
FROM active_pairs
CROSS JOIN (VALUES (4), (8), (12)) AS cutoffs(threshold)
GROUP BY threshold
ORDER BY threshold;

CREATE OR REPLACE TABLE audit_store_variation AS
WITH product_week AS (
    SELECT
        PRODUCT_ID,
        WEEK_NO,
        COUNT(DISTINCT CASE WHEN mailer <> '0' THEN mailer ELSE '0' END)
            AS mailer_variants,
        COUNT(DISTINCT CASE
            WHEN display NOT IN ('0', 'A') THEN display ELSE '0'
        END)
            AS display_variants
    FROM source.causal_data
    GROUP BY 1, 2
)
SELECT
    'mailer' AS promo_type,
    COUNT(*) AS product_weeks,
    COUNT(*) FILTER (WHERE mailer_variants > 1) AS varying_product_weeks,
    ROUND(100.0 * varying_product_weeks / product_weeks, 3)
        AS varying_pct
FROM product_week
UNION ALL
SELECT
    'display',
    COUNT(*),
    COUNT(*) FILTER (WHERE display_variants > 1),
    ROUND(100.0 * COUNT(*) FILTER (WHERE display_variants > 1) / COUNT(*), 3)
FROM product_week;

CREATE OR REPLACE TABLE audit_panel_structure AS
WITH causal_stores AS (
    SELECT DISTINCT STORE_ID FROM source.causal_data
),
store_households AS (
    SELECT
        t.STORE_ID,
        COUNT(DISTINCT t.household_key) AS households
    FROM source.transaction_data AS t
    INNER JOIN causal_stores AS s USING (STORE_ID)
    WHERE t.WEEK_NO BETWEEN 9 AND 101
    GROUP BY 1
)
SELECT
    (SELECT COUNT(DISTINCT household_key) FROM source.transaction_data)
        AS total_panel_households,
    COUNT(*) AS causal_stores,
    MIN(households) AS min_store_households,
    QUANTILE_CONT(households, 0.25) AS p25_store_households,
    MEDIAN(households) AS median_store_households,
    QUANTILE_CONT(households, 0.75) AS p75_store_households,
    MAX(households) AS max_store_households
FROM store_households;

CREATE OR REPLACE TABLE audit_store_week_traffic AS
WITH causal_stores AS (
    SELECT DISTINCT STORE_ID FROM source.causal_data
),
store_week AS (
    SELECT
        t.STORE_ID,
        t.WEEK_NO,
        COUNT(DISTINCT t.household_key) AS panel_visitors
    FROM source.transaction_data AS t
    INNER JOIN causal_stores AS s USING (STORE_ID)
    WHERE t.WEEK_NO BETWEEN 9 AND 101
    GROUP BY 1, 2
)
SELECT
    COUNT(*) AS observed_store_weeks,
    MIN(panel_visitors) AS min_visitors,
    QUANTILE_CONT(panel_visitors, 0.10) AS p10_visitors,
    QUANTILE_CONT(panel_visitors, 0.25) AS p25_visitors,
    MEDIAN(panel_visitors) AS median_visitors,
    QUANTILE_CONT(panel_visitors, 0.75) AS p75_visitors,
    QUANTILE_CONT(panel_visitors, 0.90) AS p90_visitors,
    MAX(panel_visitors) AS max_visitors,
    AVG(panel_visitors) AS avg_visitors,
    100.0 * COUNT(*) FILTER (WHERE panel_visitors <= 5) / COUNT(*)
        AS pct_5_or_fewer,
    100.0 * COUNT(*) FILTER (WHERE panel_visitors <= 10) / COUNT(*)
        AS pct_10_or_fewer
FROM store_week;
