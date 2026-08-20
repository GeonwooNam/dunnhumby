-- 목적: 팀의 고가치 지출감소 경보를 재현하고, 미래 결과를 사용하지 않는 운영 코호트를 만든다.
-- 분석시점: W80 종료(DAY 560)
-- 기준기간: W17~50 / 신호기간: W51~80 / 결과기간: W81 이후

CREATE OR REPLACE TABLE work_marketing_transaction AS
SELECT
    t.household_key,
    t.BASKET_ID,
    t.DAY,
    t.PRODUCT_ID,
    t.QUANTITY,
    t.SALES_VALUE,
    t.WEEK_NO,
    p.DEPARTMENT,
    p.COMMODITY_DESC
FROM source.transaction_data AS t
JOIN source.product AS p USING (PRODUCT_ID)
WHERE p.DEPARTMENT NOT IN ('KIOSK-GAS', 'MISC SALES TRAN')
  AND t.WEEK_NO BETWEEN 1 AND 101;

CREATE OR REPLACE TABLE work_marketing_visit AS
SELECT DISTINCT household_key, DAY, WEEK_NO
FROM work_marketing_transaction;

CREATE OR REPLACE TABLE work_marketing_baseline_customer AS
WITH baseline AS (
    SELECT
        household_key,
        COUNT(DISTINCT DAY) AS baseline_visit_days,
        SUM(SALES_VALUE) AS baseline_sales,
        COUNT(DISTINCT COMMODITY_DESC) AS baseline_commodities
    FROM work_marketing_transaction
    WHERE WEEK_NO BETWEEN 17 AND 50
    GROUP BY 1
), eligible AS (
    SELECT *
    FROM baseline
    WHERE baseline_visit_days >= 8
), cutoff AS (
    SELECT QUANTILE_CONT(baseline_sales, 0.8) AS high_value_cutoff
    FROM eligible
)
SELECT
    e.*,
    c.high_value_cutoff,
    e.baseline_sales / 34.0 AS baseline_weekly_sales,
    e.baseline_visit_days / 34.0 AS baseline_weekly_visits
FROM eligible AS e
CROSS JOIN cutoff AS c
WHERE e.baseline_sales >= c.high_value_cutoff;

CREATE OR REPLACE TABLE work_marketing_gap_signal AS
WITH baseline_gap AS (
    SELECT
        household_key,
        DAY,
        DAY - LAG(DAY) OVER (
            PARTITION BY household_key ORDER BY DAY
        ) AS visit_gap_days
    FROM work_marketing_visit
    WHERE WEEK_NO BETWEEN 17 AND 50
), baseline_normal AS (
    SELECT
        household_key,
        QUANTILE_CONT(visit_gap_days, 0.5) AS normal_gap_days
    FROM baseline_gap
    WHERE visit_gap_days IS NOT NULL
    GROUP BY 1
), evaluation_gap AS (
    SELECT
        household_key,
        DAY,
        DAY - LAG(DAY) OVER (
            PARTITION BY household_key ORDER BY DAY
        ) AS visit_gap_days
    FROM work_marketing_visit
    WHERE WEEK_NO BETWEEN 51 AND 80
), evaluation_ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY household_key ORDER BY DAY DESC
        ) AS recency_rank
    FROM evaluation_gap
    WHERE visit_gap_days IS NOT NULL
)
SELECT
    h.household_key,
    n.normal_gap_days,
    AVG(e.visit_gap_days) AS recent_three_gap_days,
    AVG(e.visit_gap_days) / NULLIF(n.normal_gap_days, 0) AS gap_ratio
FROM work_marketing_baseline_customer AS h
JOIN baseline_normal AS n USING (household_key)
LEFT JOIN evaluation_ranked AS e
  ON h.household_key = e.household_key
 AND e.recency_rank <= 3
GROUP BY 1, 2;

CREATE OR REPLACE TABLE work_marketing_category_signal AS
WITH baseline_8week_windows AS (
    SELECT * FROM RANGE(24, 51) AS t(end_week)
), baseline_8week AS (
    SELECT
        h.household_key,
        w.end_week,
        COUNT(DISTINCT t.COMMODITY_DESC) AS commodity_count
    FROM work_marketing_baseline_customer AS h
    CROSS JOIN baseline_8week_windows AS w
    LEFT JOIN work_marketing_transaction AS t
      ON h.household_key = t.household_key
     AND t.WEEK_NO BETWEEN w.end_week - 7 AND w.end_week
    GROUP BY 1, 2
), normal_8week AS (
    SELECT
        household_key,
        AVG(commodity_count) AS normal_8week_commodities
    FROM baseline_8week
    GROUP BY 1
), baseline_4week_windows AS (
    SELECT * FROM RANGE(20, 51) AS t(end_week)
), baseline_4week AS (
    SELECT
        h.household_key,
        w.end_week,
        COUNT(DISTINCT t.COMMODITY_DESC) AS commodity_count
    FROM work_marketing_baseline_customer AS h
    CROSS JOIN baseline_4week_windows AS w
    LEFT JOIN work_marketing_transaction AS t
      ON h.household_key = t.household_key
     AND t.WEEK_NO BETWEEN w.end_week - 3 AND w.end_week
    GROUP BY 1, 2
), normal_4week AS (
    SELECT
        household_key,
        AVG(commodity_count) AS normal_4week_commodities
    FROM baseline_4week
    GROUP BY 1
), recent_8week AS (
    SELECT
        h.household_key,
        COUNT(DISTINCT t.COMMODITY_DESC) AS recent_8week_commodities
    FROM work_marketing_baseline_customer AS h
    LEFT JOIN work_marketing_transaction AS t
      ON h.household_key = t.household_key
     AND t.WEEK_NO BETWEEN 73 AND 80
    GROUP BY 1
)
SELECT
    n8.household_key,
    n4.normal_4week_commodities,
    n8.normal_8week_commodities,
    r.recent_8week_commodities,
    r.recent_8week_commodities
        / NULLIF(n8.normal_8week_commodities, 0) AS category_ratio
FROM normal_8week AS n8
JOIN normal_4week AS n4 USING (household_key)
JOIN recent_8week AS r USING (household_key);

CREATE OR REPLACE TABLE mart_marketing_risk_cohort AS
SELECT
    b.*,
    g.normal_gap_days,
    g.recent_three_gap_days,
    g.gap_ratio,
    c.normal_4week_commodities,
    c.normal_8week_commodities,
    c.recent_8week_commodities,
    c.category_ratio,
    CAST(g.gap_ratio >= 1.5 AS INTEGER) AS is_stage1_monitor,
    CAST(
        g.gap_ratio >= 1.5
        AND c.category_ratio < 0.7
        AS INTEGER
    ) AS is_stage2_target,
    CAST(EXISTS (
        SELECT 1
        FROM work_marketing_visit AS v
        WHERE v.household_key = b.household_key
          AND v.WEEK_NO BETWEEN 81 AND 101
    ) AS INTEGER) AS holdout_returned
FROM work_marketing_baseline_customer AS b
JOIN work_marketing_gap_signal AS g USING (household_key)
JOIN work_marketing_category_signal AS c USING (household_key);

CREATE OR REPLACE TABLE audit_marketing_risk_definition AS
SELECT
    '01_all_high_value' AS sample_definition,
    COUNT(*) AS households,
    SUM(is_stage1_monitor) AS stage1_households,
    SUM(CAST(category_ratio < 0.7 AS INTEGER)) AS category_signal_households,
    SUM(is_stage2_target) AS stage2_households
FROM mart_marketing_risk_cohort
UNION ALL
SELECT
    '02_published_returning_subset',
    COUNT(*),
    SUM(is_stage1_monitor),
    SUM(CAST(category_ratio < 0.7 AS INTEGER)),
    SUM(is_stage2_target)
FROM mart_marketing_risk_cohort
WHERE holdout_returned = 1;

