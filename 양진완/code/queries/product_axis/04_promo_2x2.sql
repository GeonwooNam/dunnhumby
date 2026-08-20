-- 목적: 점포-주 패널 트래픽을 보정한 전단/진열 2x2 기술 성과를 비교한다.
-- 입력: mart_product_store_week
-- 출력: mart_promo_2x2, mart_promo_synergy, mart_promo_traffic_strata
-- 주 분석은 최소 8주 판매 및 점포-주 방문 패널 10명 이상 표본이다.

CREATE OR REPLACE TABLE mart_promo_2x2 AS
WITH sampled AS (
    SELECT 'active_8_all_traffic' AS sample_definition, *
    FROM mart_product_store_week
    WHERE sold_weeks >= 8 AND panel_visitors > 0
      AND promo_group IN ('none', 'display_only', 'mailer_only', 'both')
    UNION ALL
    SELECT 'active_8_visitors_5plus', *
    FROM mart_product_store_week
    WHERE sold_weeks >= 8 AND panel_visitors >= 5
      AND promo_group IN ('none', 'display_only', 'mailer_only', 'both')
    UNION ALL
    SELECT 'active_8_visitors_10plus', *
    FROM mart_product_store_week
    WHERE sold_weeks >= 8 AND panel_visitors >= 10
      AND promo_group IN ('none', 'display_only', 'mailer_only', 'both')
    UNION ALL
    SELECT 'active_12_visitors_10plus', *
    FROM mart_product_store_week
    WHERE sold_weeks >= 12 AND panel_visitors >= 10
      AND promo_group IN ('none', 'display_only', 'mailer_only', 'both')
),
summary AS (
    SELECT
        sample_definition,
        promo_group,
        COUNT(*) AS pair_weeks,
        COUNT(DISTINCT PRODUCT_ID) AS products,
        COUNT(DISTINCT STORE_ID) AS stores,
        COUNT(DISTINCT (PRODUCT_ID, STORE_ID)) AS product_store_pairs,
        AVG(panel_visitors) AS avg_panel_visitors,
        SUM(weekly_sales) AS total_panel_sales,
        AVG(weekly_sales) AS avg_weekly_sales,
        MEDIAN(weekly_sales) AS median_weekly_sales,
        AVG(purchase_incidence) AS purchase_incidence_rate,
        AVG(buyer_penetration_rate) AS avg_buyer_penetration_rate,
        AVG(sales_per_visitor) AS avg_sales_per_visitor,
        AVG(basket_share_rate) AS avg_basket_share_rate,
        AVG(store_sales_share_rate) AS avg_store_sales_share_rate,
        AVG(category_sales_share_rate) AS avg_category_sales_share_rate
    FROM sampled
    GROUP BY 1, 2
),
with_baseline AS (
    SELECT
        *,
        MAX(avg_weekly_sales) FILTER (WHERE promo_group = 'none')
            OVER (PARTITION BY sample_definition) AS none_avg_sales,
        MAX(purchase_incidence_rate) FILTER (WHERE promo_group = 'none')
            OVER (PARTITION BY sample_definition) AS none_incidence,
        MAX(avg_buyer_penetration_rate) FILTER (WHERE promo_group = 'none')
            OVER (PARTITION BY sample_definition) AS none_buyer_penetration,
        MAX(avg_sales_per_visitor) FILTER (WHERE promo_group = 'none')
            OVER (PARTITION BY sample_definition) AS none_sales_per_visitor,
        MAX(avg_basket_share_rate) FILTER (WHERE promo_group = 'none')
            OVER (PARTITION BY sample_definition) AS none_basket_share,
        MAX(avg_store_sales_share_rate) FILTER (WHERE promo_group = 'none')
            OVER (PARTITION BY sample_definition) AS none_store_sales_share,
        MAX(avg_category_sales_share_rate) FILTER (WHERE promo_group = 'none')
            OVER (PARTITION BY sample_definition) AS none_category_sales_share
    FROM summary
)
SELECT
    *,
    100.0 * (avg_weekly_sales / NULLIF(none_avg_sales, 0) - 1)
        AS raw_sales_lift_vs_none_pct,
    100.0 * (purchase_incidence_rate - none_incidence)
        AS purchase_incidence_diff_pp,
    100.0 * (
        avg_buyer_penetration_rate / NULLIF(none_buyer_penetration, 0) - 1
    ) AS buyer_penetration_lift_pct,
    100.0 * (
        avg_sales_per_visitor / NULLIF(none_sales_per_visitor, 0) - 1
    ) AS sales_per_visitor_lift_pct,
    100.0 * (
        avg_basket_share_rate / NULLIF(none_basket_share, 0) - 1
    ) AS basket_share_lift_pct,
    100.0 * (
        avg_store_sales_share_rate / NULLIF(none_store_sales_share, 0) - 1
    ) AS store_sales_share_lift_pct,
    100.0 * (
        avg_category_sales_share_rate / NULLIF(none_category_sales_share, 0) - 1
    ) AS category_sales_share_lift_pct
FROM with_baseline
ORDER BY
    CASE sample_definition
        WHEN 'active_8_all_traffic' THEN 1
        WHEN 'active_8_visitors_5plus' THEN 2
        WHEN 'active_8_visitors_10plus' THEN 3
        ELSE 4
    END,
    CASE promo_group
        WHEN 'none' THEN 1
        WHEN 'display_only' THEN 2
        WHEN 'mailer_only' THEN 3
        ELSE 4
    END;

CREATE OR REPLACE TABLE mart_promo_synergy AS
WITH pivoted AS (
    SELECT
        sample_definition,
        MAX(avg_sales_per_visitor) FILTER (WHERE promo_group = 'none')
            AS none_sales_per_visitor,
        MAX(avg_sales_per_visitor) FILTER (WHERE promo_group = 'display_only')
            AS display_sales_per_visitor,
        MAX(avg_sales_per_visitor) FILTER (WHERE promo_group = 'mailer_only')
            AS mailer_sales_per_visitor,
        MAX(avg_sales_per_visitor) FILTER (WHERE promo_group = 'both')
            AS both_sales_per_visitor,
        MAX(avg_buyer_penetration_rate) FILTER (WHERE promo_group = 'none')
            AS none_buyer_penetration,
        MAX(avg_buyer_penetration_rate) FILTER (WHERE promo_group = 'display_only')
            AS display_buyer_penetration,
        MAX(avg_buyer_penetration_rate) FILTER (WHERE promo_group = 'mailer_only')
            AS mailer_buyer_penetration,
        MAX(avg_buyer_penetration_rate) FILTER (WHERE promo_group = 'both')
            AS both_buyer_penetration
    FROM mart_promo_2x2
    GROUP BY sample_definition
)
SELECT
    *,
    both_sales_per_visitor - mailer_sales_per_visitor
        - display_sales_per_visitor + none_sales_per_visitor
        AS additive_sales_per_visitor_increment,
    100.0 * (
        both_sales_per_visitor - mailer_sales_per_visitor
        - display_sales_per_visitor + none_sales_per_visitor
    ) / NULLIF(none_sales_per_visitor, 0)
        AS additive_sales_per_visitor_increment_pct,
    100.0 * (
        both_buyer_penetration - mailer_buyer_penetration
        - display_buyer_penetration + none_buyer_penetration
    ) AS additive_buyer_penetration_increment_pp
FROM pivoted
ORDER BY sample_definition;

CREATE OR REPLACE TABLE mart_promo_traffic_strata AS
WITH store_week_traffic AS (
    SELECT
        STORE_ID,
        WEEK_NO,
        panel_visitors,
        NTILE(4) OVER (ORDER BY panel_visitors) AS traffic_quartile
    FROM work_store_week_context
),
joined AS (
    SELECT p.*, t.traffic_quartile
    FROM mart_product_store_week AS p
    INNER JOIN store_week_traffic AS t USING (STORE_ID, WEEK_NO)
    WHERE p.sold_weeks >= 8
      AND p.promo_group IN ('none', 'display_only', 'mailer_only', 'both')
)
SELECT
    traffic_quartile,
    promo_group,
    COUNT(*) AS pair_weeks,
    AVG(panel_visitors) AS avg_panel_visitors,
    AVG(purchase_incidence) AS purchase_incidence_rate,
    AVG(buyer_penetration_rate) AS avg_buyer_penetration_rate,
    AVG(sales_per_visitor) AS avg_sales_per_visitor,
    AVG(basket_share_rate) AS avg_basket_share_rate
FROM joined
GROUP BY 1, 2
ORDER BY traffic_quartile,
    CASE promo_group
        WHEN 'none' THEN 1
        WHEN 'display_only' THEN 2
        WHEN 'mailer_only' THEN 3
        ELSE 4
    END;
