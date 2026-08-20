-- 목적: 고정 시작일을 가진 Campaign 18 배정 여부와 이후 성과의 조건부 연관성을 비교한다.
-- 비교기간: 28일 DAY 587~614 / 56일 DAY 587~642
-- 주의: 비무작위 캠페인이므로 인과효과가 아니다. 쿠폰 사용 여부는 처치로 사용하지 않는다.

CREATE OR REPLACE TABLE mart_campaign18_customer_outcome AS
SELECT
    r.*,
    COUNT(DISTINCT t.DAY) FILTER (
        WHERE t.DAY BETWEEN 587 AND 614
    ) AS visit_days_28,
    COALESCE(SUM(t.SALES_VALUE) FILTER (
        WHERE t.DAY BETWEEN 587 AND 614
    ), 0) AS sales_28,
    COUNT(DISTINCT t.COMMODITY_DESC) FILTER (
        WHERE t.DAY BETWEEN 587 AND 614
    ) AS commodities_28,
    COUNT(DISTINCT t.DAY) FILTER (
        WHERE t.DAY BETWEEN 587 AND 642
    ) AS visit_days_56,
    COALESCE(SUM(t.SALES_VALUE) FILTER (
        WHERE t.DAY BETWEEN 587 AND 642
    ), 0) AS sales_56,
    COUNT(DISTINCT t.COMMODITY_DESC) FILTER (
        WHERE t.DAY BETWEEN 587 AND 642
    ) AS commodities_56
FROM work_marketing_stage2_status AS r
LEFT JOIN work_marketing_transaction AS t USING (household_key)
GROUP BY ALL;

CREATE OR REPLACE TABLE work_campaign18_customer_metric AS
SELECT
    *,
    CAST(visit_days_28 > 0 AS DOUBLE) AS returned_28,
    CAST(visit_days_56 > 0 AS DOUBLE) AS returned_56,
    visit_days_28 / NULLIF(baseline_weekly_visits * 4, 0)
        AS visit_retention_28,
    sales_28 / NULLIF(baseline_weekly_sales * 4, 0)
        AS sales_retention_28,
    commodities_28 / NULLIF(normal_4week_commodities, 0)
        AS category_recovery_28,
    visit_days_56 / NULLIF(baseline_weekly_visits * 8, 0)
        AS visit_retention_56,
    sales_56 / NULLIF(baseline_weekly_sales * 8, 0)
        AS sales_retention_56,
    commodities_56 / NULLIF(normal_8week_commodities, 0)
        AS category_recovery_56
FROM mart_campaign18_customer_outcome;

CREATE OR REPLACE TABLE audit_campaign18_baseline_balance AS
SELECT
    campaign18_assigned,
    COUNT(*) AS households,
    SUM(campaign18_redeemed) AS coupon_redeemers,
    AVG(baseline_sales) AS avg_baseline_sales,
    AVG(baseline_visit_days) AS avg_baseline_visit_days,
    AVG(normal_8week_commodities) AS avg_normal_8week_commodities,
    AVG(gap_ratio) AS avg_gap_ratio,
    AVG(category_ratio) AS avg_category_ratio
FROM work_campaign18_customer_metric
GROUP BY 1;

CREATE OR REPLACE TABLE work_campaign18_metric_long AS
SELECT household_key, campaign18_assigned, 'return_rate_28' AS metric,
       returned_28 AS metric_value
FROM work_campaign18_customer_metric
UNION ALL
SELECT household_key, campaign18_assigned, 'visit_days_28', visit_days_28
FROM work_campaign18_customer_metric
UNION ALL
SELECT household_key, campaign18_assigned, 'sales_28', sales_28
FROM work_campaign18_customer_metric
UNION ALL
SELECT household_key, campaign18_assigned, 'visit_retention_28', visit_retention_28
FROM work_campaign18_customer_metric
UNION ALL
SELECT household_key, campaign18_assigned, 'sales_retention_28', sales_retention_28
FROM work_campaign18_customer_metric
UNION ALL
SELECT household_key, campaign18_assigned, 'category_recovery_28', category_recovery_28
FROM work_campaign18_customer_metric
UNION ALL
SELECT household_key, campaign18_assigned, 'return_rate_56', returned_56
FROM work_campaign18_customer_metric
UNION ALL
SELECT household_key, campaign18_assigned, 'visit_days_56', visit_days_56
FROM work_campaign18_customer_metric
UNION ALL
SELECT household_key, campaign18_assigned, 'sales_56', sales_56
FROM work_campaign18_customer_metric
UNION ALL
SELECT household_key, campaign18_assigned, 'visit_retention_56', visit_retention_56
FROM work_campaign18_customer_metric
UNION ALL
SELECT household_key, campaign18_assigned, 'sales_retention_56', sales_retention_56
FROM work_campaign18_customer_metric
UNION ALL
SELECT household_key, campaign18_assigned, 'category_recovery_56', category_recovery_56
FROM work_campaign18_customer_metric;

CREATE OR REPLACE TABLE mart_campaign18_raw_group AS
SELECT
    campaign18_assigned,
    metric,
    COUNT(*) AS households,
    AVG(metric_value) AS mean_value,
    QUANTILE_CONT(metric_value, 0.5) AS median_value
FROM work_campaign18_metric_long
GROUP BY 1, 2;

CREATE OR REPLACE TABLE mart_campaign18_raw_difference AS
SELECT
    a.metric,
    u.households AS unassigned_households,
    a.households AS assigned_households,
    u.mean_value AS unassigned_mean,
    a.mean_value AS assigned_mean,
    a.mean_value - u.mean_value AS raw_difference,
    u.median_value AS unassigned_median,
    a.median_value AS assigned_median
FROM mart_campaign18_raw_group AS a
JOIN mart_campaign18_raw_group AS u USING (metric)
WHERE a.campaign18_assigned = 1
  AND u.campaign18_assigned = 0;

CREATE OR REPLACE TABLE work_campaign18_stratum AS
WITH ranked AS (
    SELECT
        *,
        PERCENT_RANK() OVER (ORDER BY baseline_sales) AS sales_rank,
        PERCENT_RANK() OVER (ORDER BY baseline_visit_days) AS visit_rank,
        PERCENT_RANK() OVER (ORDER BY normal_8week_commodities) AS category_rank
    FROM work_campaign18_customer_metric
)
SELECT
    *,
    NTILE(3) OVER (
        ORDER BY sales_rank + visit_rank + category_rank, household_key
    ) AS engagement_stratum
FROM ranked;

CREATE OR REPLACE TABLE work_campaign18_stratum_metric AS
SELECT s.engagement_stratum, m.*
FROM work_campaign18_stratum AS s
JOIN work_campaign18_metric_long AS m USING (household_key);

CREATE OR REPLACE TABLE mart_campaign18_stratum_detail AS
SELECT
    engagement_stratum,
    campaign18_assigned,
    metric,
    COUNT(*) AS households,
    AVG(metric_value) AS mean_value,
    QUANTILE_CONT(metric_value, 0.5) AS median_value
FROM work_campaign18_stratum_metric
GROUP BY 1, 2, 3;

CREATE OR REPLACE TABLE mart_campaign18_adjusted_difference AS
WITH stratum_size AS (
    SELECT engagement_stratum, COUNT(*) AS stratum_households
    FROM work_campaign18_stratum
    GROUP BY 1
), paired AS (
    SELECT
        a.metric,
        a.engagement_stratum,
        s.stratum_households,
        u.households AS unassigned_households,
        a.households AS assigned_households,
        a.mean_value - u.mean_value AS within_stratum_difference
    FROM mart_campaign18_stratum_detail AS a
    JOIN mart_campaign18_stratum_detail AS u
      ON a.engagement_stratum = u.engagement_stratum
     AND a.metric = u.metric
    JOIN stratum_size AS s
      ON a.engagement_stratum = s.engagement_stratum
    WHERE a.campaign18_assigned = 1
      AND u.campaign18_assigned = 0
), common_total AS (
    SELECT metric, SUM(stratum_households) AS common_support_households
    FROM paired
    GROUP BY 1
), adjusted AS (
    SELECT
        p.metric,
        COUNT(*) AS common_support_strata,
        MAX(t.common_support_households) AS common_support_households,
        SUM(
            p.within_stratum_difference
            * p.stratum_households / t.common_support_households
        ) AS stratified_difference
    FROM paired AS p
    JOIN common_total AS t USING (metric)
    GROUP BY 1
)
SELECT
    a.metric,
    r.raw_difference,
    a.stratified_difference,
    a.common_support_strata,
    a.common_support_households
FROM adjusted AS a
JOIN mart_campaign18_raw_difference AS r USING (metric);
