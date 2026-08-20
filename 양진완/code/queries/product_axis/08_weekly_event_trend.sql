-- 목적: 주차별 트래픽 보정 성과와 고립된 1주 행사 전후 추이를 기술한다.
-- 입력: mart_product_store_week
-- 출력: mart_weekly_promotion_trend, work_clean_events, mart_event_trend
-- 행사 전후 4주 안에 다른 프로모션이 없는 이벤트만 사용한다.

CREATE OR REPLACE TABLE mart_weekly_promotion_trend AS
SELECT
    WEEK_NO,
    promo_group,
    COUNT(*) AS pair_weeks,
    COUNT(DISTINCT PRODUCT_ID) AS products,
    COUNT(DISTINCT STORE_ID) AS stores,
    SUM(weekly_sales) AS total_sales,
    AVG(weekly_sales) AS avg_weekly_sales,
    AVG(purchase_incidence) AS sales_incidence_rate,
    AVG(buyer_count) AS avg_buyer_count,
    AVG(sales_per_visitor) AS avg_sales_per_visitor,
    AVG(buyer_penetration_rate) AS avg_buyer_penetration_rate,
    AVG(basket_share_rate) AS avg_basket_share_rate
FROM mart_product_store_week
WHERE sold_weeks >= 8
  AND panel_visitors >= 10
  AND promo_group IN ('none', 'display_only', 'mailer_only', 'both')
GROUP BY 1, 2
ORDER BY WEEK_NO,
    CASE promo_group
        WHEN 'none' THEN 1
        WHEN 'display_only' THEN 2
        WHEN 'mailer_only' THEN 3
        ELSE 4
    END;

CREATE OR REPLACE TABLE work_clean_events AS
WITH marked AS (
    SELECT
        PRODUCT_ID,
        STORE_ID,
        WEEK_NO,
        first_week,
        last_week,
        promo_group,
        promo_code_conflict,
        CASE WHEN is_mailer = 1 OR is_display = 1 THEN 1 ELSE 0 END
            AS is_promo,
        MAX(CASE WHEN is_mailer = 1 OR is_display = 1 THEN 1 ELSE 0 END)
            OVER (
                PARTITION BY PRODUCT_ID, STORE_ID
                ORDER BY WEEK_NO
                ROWS BETWEEN 4 PRECEDING AND 1 PRECEDING
            ) AS prior_4week_promo,
        MAX(CASE WHEN is_mailer = 1 OR is_display = 1 THEN 1 ELSE 0 END)
            OVER (
                PARTITION BY PRODUCT_ID, STORE_ID
                ORDER BY WEEK_NO
                ROWS BETWEEN 1 FOLLOWING AND 4 FOLLOWING
            ) AS next_4week_promo
        ,
        MIN(promotion_record_present) OVER (
            PARTITION BY PRODUCT_ID, STORE_ID
            ORDER BY WEEK_NO
            ROWS BETWEEN 4 PRECEDING AND 1 PRECEDING
        ) AS prior_4week_observed,
        MIN(promotion_record_present) OVER (
            PARTITION BY PRODUCT_ID, STORE_ID
            ORDER BY WEEK_NO
            ROWS BETWEEN 1 FOLLOWING AND 4 FOLLOWING
        ) AS next_4week_observed
        ,
        MIN(CASE
            WHEN promotion_record_present = 1 AND promo_code_conflict = 0
            THEN 1 ELSE 0
        END) OVER (
            PARTITION BY PRODUCT_ID, STORE_ID
            ORDER BY WEEK_NO
            ROWS BETWEEN 4 PRECEDING AND 1 PRECEDING
        ) AS prior_4week_usable,
        MIN(CASE
            WHEN promotion_record_present = 1 AND promo_code_conflict = 0
            THEN 1 ELSE 0
        END) OVER (
            PARTITION BY PRODUCT_ID, STORE_ID
            ORDER BY WEEK_NO
            ROWS BETWEEN 1 FOLLOWING AND 4 FOLLOWING
        ) AS next_4week_usable
    FROM mart_product_store_week
    WHERE sold_weeks >= 8
)
SELECT
    ROW_NUMBER() OVER (ORDER BY PRODUCT_ID, STORE_ID, WEEK_NO) AS event_id,
    PRODUCT_ID,
    STORE_ID,
    WEEK_NO AS event_week,
    promo_group AS event_group
FROM marked
WHERE is_promo = 1
  AND promo_code_conflict = 0
  AND WEEK_NO - first_week >= 4
  AND last_week - WEEK_NO >= 4
  AND COALESCE(prior_4week_promo, 0) = 0
  AND COALESCE(next_4week_promo, 0) = 0
  AND prior_4week_observed = 1
  AND next_4week_observed = 1
  AND prior_4week_usable = 1
  AND next_4week_usable = 1;

CREATE OR REPLACE TABLE mart_event_trend AS
WITH event_rows_raw AS (
    SELECT
        e.event_id,
        e.event_group,
        p.WEEK_NO - e.event_week AS relative_week,
        p.weekly_sales,
        p.purchase_incidence,
        p.buyer_count,
        p.panel_visitors,
        p.sales_per_visitor,
        p.buyer_penetration_rate,
        p.basket_share_rate
    FROM work_clean_events AS e
    INNER JOIN mart_product_store_week AS p
        ON p.PRODUCT_ID = e.PRODUCT_ID
       AND p.STORE_ID = e.STORE_ID
       AND p.WEEK_NO BETWEEN e.event_week - 4 AND e.event_week + 4
),
qualified_events AS (
    SELECT event_id
    FROM event_rows_raw
    GROUP BY event_id
    HAVING COUNT(*) = 9 AND MIN(panel_visitors) >= 5
),
event_rows AS (
    SELECT r.*
    FROM event_rows_raw AS r
    INNER JOIN qualified_events AS q USING (event_id)
),
summary AS (
    SELECT
        event_group,
        relative_week,
        COUNT(*) AS event_observations,
        COUNT(DISTINCT event_id) AS clean_events,
        AVG(weekly_sales) AS avg_weekly_sales,
        MEDIAN(weekly_sales) AS median_weekly_sales,
        AVG(purchase_incidence) AS sales_incidence_rate,
        AVG(buyer_count) AS avg_buyer_count,
        AVG(panel_visitors) AS avg_panel_visitors,
        AVG(sales_per_visitor) AS avg_sales_per_visitor,
        AVG(buyer_penetration_rate) AS avg_buyer_penetration_rate,
        AVG(basket_share_rate) AS avg_basket_share_rate
    FROM event_rows
    GROUP BY 1, 2
)
SELECT
    *,
    100.0 * avg_weekly_sales / NULLIF(
        AVG(avg_weekly_sales) FILTER (
            WHERE relative_week BETWEEN -4 AND -1
        ) OVER (PARTITION BY event_group),
        0
    ) AS pre_period_sales_index
    ,
    100.0 * avg_sales_per_visitor / NULLIF(
        AVG(avg_sales_per_visitor) FILTER (
            WHERE relative_week BETWEEN -4 AND -1
        ) OVER (PARTITION BY event_group),
        0
    ) AS pre_period_sales_per_visitor_index
FROM summary
ORDER BY
    CASE event_group
        WHEN 'display_only' THEN 1
        WHEN 'mailer_only' THEN 2
        WHEN 'both' THEN 3
        ELSE 4
    END,
    relative_week;
