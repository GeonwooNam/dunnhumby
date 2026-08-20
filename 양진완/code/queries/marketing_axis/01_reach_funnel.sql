-- 목적: W80 종료 시점의 2단계 위험고객에게 이후 캠페인이 얼마나 도달했는지 집계한다.
-- 주의: campaign_table은 배정 기록이며 실제 우편 열람·쿠폰 인지를 뜻하지 않는다.

CREATE OR REPLACE TABLE work_marketing_campaign_assignment AS
WITH coupon_count AS (
    SELECT
        CAMPAIGN,
        COUNT(DISTINCT COUPON_UPC) AS campaign_coupon_count
    FROM source.coupon
    GROUP BY 1
)
SELECT
    c.household_key,
    c.CAMPAIGN,
    d.DESCRIPTION AS campaign_type,
    d.START_DAY,
    d.END_DAY,
    COALESCE(q.campaign_coupon_count, 0) AS campaign_coupon_count
FROM source.campaign_table AS c
JOIN source.campaign_desc AS d USING (CAMPAIGN)
LEFT JOIN coupon_count AS q USING (CAMPAIGN);

CREATE OR REPLACE TABLE work_marketing_stage2_status AS
SELECT
    r.*,
    CAST(EXISTS (
        SELECT 1
        FROM work_marketing_campaign_assignment AS c
        WHERE c.household_key = r.household_key
          AND c.START_DAY BETWEEN 561 AND 588
    ) AS INTEGER) AS campaign_assigned_4week,
    CAST(EXISTS (
        SELECT 1
        FROM work_marketing_campaign_assignment AS c
        WHERE c.household_key = r.household_key
          AND c.START_DAY BETWEEN 561 AND 616
    ) AS INTEGER) AS campaign_assigned_8week,
    CAST(EXISTS (
        SELECT 1
        FROM source.coupon_redempt AS x
        JOIN source.campaign_table AS a
          ON x.household_key = a.household_key
         AND x.CAMPAIGN = a.CAMPAIGN
        JOIN source.campaign_desc AS d
          ON x.CAMPAIGN = d.CAMPAIGN
        WHERE x.household_key = r.household_key
          AND d.START_DAY BETWEEN 561 AND 588
          AND x.DAY BETWEEN 561 AND 588
    ) AS INTEGER) AS coupon_redeemed_4week,
    CAST(EXISTS (
        SELECT 1
        FROM source.coupon_redempt AS x
        JOIN source.campaign_table AS a
          ON x.household_key = a.household_key
         AND x.CAMPAIGN = a.CAMPAIGN
        JOIN source.campaign_desc AS d
          ON x.CAMPAIGN = d.CAMPAIGN
        WHERE x.household_key = r.household_key
          AND d.START_DAY BETWEEN 561 AND 616
          AND x.DAY BETWEEN 561 AND 616
    ) AS INTEGER) AS coupon_redeemed_8week,
    CAST(EXISTS (
        SELECT 1
        FROM source.campaign_table AS c
        WHERE c.household_key = r.household_key
          AND c.CAMPAIGN = 18
    ) AS INTEGER) AS campaign18_assigned,
    CAST(EXISTS (
        SELECT 1
        FROM source.coupon_redempt AS x
        WHERE x.household_key = r.household_key
          AND x.CAMPAIGN = 18
          AND x.DAY BETWEEN 587 AND 642
    ) AS INTEGER) AS campaign18_redeemed
FROM mart_marketing_risk_cohort AS r
WHERE r.is_stage2_target = 1;

CREATE OR REPLACE TABLE audit_marketing_reach_funnel AS
WITH counts AS (
    SELECT
        (SELECT COUNT(*) FROM mart_marketing_risk_cohort) AS high_value_n,
        (SELECT SUM(is_stage1_monitor) FROM mart_marketing_risk_cohort) AS stage1_n,
        (SELECT SUM(is_stage2_target) FROM mart_marketing_risk_cohort) AS stage2_n,
        (SELECT SUM(campaign_assigned_4week) FROM work_marketing_stage2_status) AS assigned4_n,
        (SELECT SUM(coupon_redeemed_4week) FROM work_marketing_stage2_status) AS redeemed4_n,
        (SELECT SUM(campaign_assigned_8week) FROM work_marketing_stage2_status) AS assigned8_n,
        (SELECT SUM(coupon_redeemed_8week) FROM work_marketing_stage2_status) AS redeemed8_n
)
SELECT 1 AS step_order, 'risk' AS window, 'high_value_baseline' AS funnel_stage,
       high_value_n AS households, high_value_n AS denominator,
       1.0 AS rate
FROM counts
UNION ALL
SELECT 2, 'risk', 'stage1_monitor', stage1_n, high_value_n,
       stage1_n * 1.0 / high_value_n
FROM counts
UNION ALL
SELECT 3, 'risk', 'stage2_target', stage2_n, high_value_n,
       stage2_n * 1.0 / high_value_n
FROM counts
UNION ALL
SELECT 4, '4week', 'campaign_assigned', assigned4_n, stage2_n,
       assigned4_n * 1.0 / stage2_n
FROM counts
UNION ALL
SELECT 5, '4week', 'coupon_redeemed', redeemed4_n, assigned4_n,
       redeemed4_n * 1.0 / NULLIF(assigned4_n, 0)
FROM counts
UNION ALL
SELECT 6, '8week', 'campaign_assigned', assigned8_n, stage2_n,
       assigned8_n * 1.0 / stage2_n
FROM counts
UNION ALL
SELECT 7, '8week', 'coupon_redeemed', redeemed8_n, assigned8_n,
       redeemed8_n * 1.0 / NULLIF(assigned8_n, 0)
FROM counts;

CREATE OR REPLACE TABLE mart_marketing_campaign_reach_detail AS
SELECT
    c.CAMPAIGN,
    c.campaign_type,
    c.START_DAY,
    c.END_DAY,
    MAX(c.campaign_coupon_count) AS coupon_count,
    COUNT(DISTINCT c.household_key) AS assigned_stage2_households,
    COUNT(DISTINCT CASE WHEN x.household_key IS NOT NULL THEN c.household_key END)
        AS redeemed_stage2_households
FROM work_marketing_campaign_assignment AS c
JOIN work_marketing_stage2_status AS r USING (household_key)
LEFT JOIN source.coupon_redempt AS x
  ON c.household_key = x.household_key
 AND c.CAMPAIGN = x.CAMPAIGN
 AND x.DAY BETWEEN c.START_DAY AND c.END_DAY
WHERE c.START_DAY BETWEEN 561 AND 616
GROUP BY 1, 2, 3, 4;
