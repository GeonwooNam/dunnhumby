-- 목적: 카테고리와 브랜드 유형별 트래픽 보정 프로모션 성과를 비교한다.
-- 입력: mart_product_store_week, source.product
-- 출력: mart_segment_response
-- 상품 구성 확인용 기술 분석이며 카테고리별 인과효과를 뜻하지 않는다.

CREATE OR REPLACE TABLE mart_segment_response AS
WITH panel_product AS (
    SELECT
        p.*,
        pr.DEPARTMENT,
        pr.COMMODITY_DESC,
        pr.BRAND
    FROM mart_product_store_week AS p
    INNER JOIN source.product AS pr USING (PRODUCT_ID)
    WHERE p.sold_weeks >= 8
      AND p.panel_visitors >= 10
      AND p.promo_group IN ('none', 'display_only', 'mailer_only', 'both')
),
top_commodities AS (
    SELECT COMMODITY_DESC
    FROM panel_product
    WHERE COMMODITY_DESC IS NOT NULL
    GROUP BY 1
    ORDER BY SUM(weekly_sales) DESC
    LIMIT 30
),
segmented AS (
    SELECT
        'department' AS segment_type,
        DEPARTMENT AS segment_value,
        * EXCLUDE (DEPARTMENT, COMMODITY_DESC, BRAND)
    FROM panel_product
    WHERE DEPARTMENT IS NOT NULL
    UNION ALL
    SELECT
        'commodity_top30',
        p.COMMODITY_DESC,
        p.* EXCLUDE (DEPARTMENT, COMMODITY_DESC, BRAND)
    FROM panel_product AS p
    INNER JOIN top_commodities AS t USING (COMMODITY_DESC)
    UNION ALL
    SELECT
        'brand',
        BRAND,
        * EXCLUDE (DEPARTMENT, COMMODITY_DESC, BRAND)
    FROM panel_product
    WHERE BRAND IS NOT NULL
),
summary AS (
    SELECT
        segment_type,
        segment_value,
        promo_group,
        COUNT(*) AS pair_weeks,
        COUNT(DISTINCT PRODUCT_ID) AS products,
        COUNT(DISTINCT STORE_ID) AS stores,
        COUNT(DISTINCT (PRODUCT_ID, STORE_ID)) AS product_store_pairs,
        AVG(weekly_sales) AS avg_weekly_sales,
        MEDIAN(weekly_sales) AS median_weekly_sales,
        AVG(purchase_incidence) AS sales_incidence_rate,
        AVG(buyer_count) AS avg_buyer_count,
        AVG(sales_per_visitor) AS avg_sales_per_visitor,
        AVG(buyer_penetration_rate) AS avg_buyer_penetration_rate,
        AVG(basket_share_rate) AS avg_basket_share_rate,
        AVG(store_sales_share_rate) AS avg_store_sales_share_rate,
        AVG(category_sales_share_rate) AS avg_category_sales_share_rate
    FROM segmented
    GROUP BY 1, 2, 3
    HAVING COUNT(*) >= 100 AND COUNT(DISTINCT PRODUCT_ID) >= 5
),
with_baseline AS (
    SELECT
        *,
        MAX(avg_weekly_sales) FILTER (WHERE promo_group = 'none')
            OVER (PARTITION BY segment_type, segment_value) AS none_avg_sales,
        MAX(sales_incidence_rate) FILTER (WHERE promo_group = 'none')
            OVER (PARTITION BY segment_type, segment_value) AS none_incidence,
        MAX(avg_sales_per_visitor) FILTER (WHERE promo_group = 'none')
            OVER (PARTITION BY segment_type, segment_value) AS none_sales_per_visitor,
        MAX(avg_buyer_penetration_rate) FILTER (WHERE promo_group = 'none')
            OVER (PARTITION BY segment_type, segment_value) AS none_buyer_penetration,
        MAX(avg_basket_share_rate) FILTER (WHERE promo_group = 'none')
            OVER (PARTITION BY segment_type, segment_value) AS none_basket_share,
        MAX(avg_category_sales_share_rate) FILTER (WHERE promo_group = 'none')
            OVER (PARTITION BY segment_type, segment_value) AS none_category_sales_share
    FROM summary
)
SELECT
    *,
    100.0 * (avg_weekly_sales / NULLIF(none_avg_sales, 0) - 1)
        AS raw_sales_lift_vs_none_pct,
    100.0 * (sales_incidence_rate - none_incidence)
        AS incidence_diff_pp,
    100.0 * (avg_sales_per_visitor / NULLIF(none_sales_per_visitor, 0) - 1)
        AS sales_per_visitor_lift_pct,
    100.0 * (
        avg_buyer_penetration_rate / NULLIF(none_buyer_penetration, 0) - 1
    ) AS buyer_penetration_lift_pct,
    100.0 * (avg_basket_share_rate / NULLIF(none_basket_share, 0) - 1)
        AS basket_share_lift_pct,
    100.0 * (
        avg_category_sales_share_rate / NULLIF(none_category_sales_share, 0) - 1
    ) AS category_sales_share_lift_pct
FROM with_baseline
ORDER BY segment_type, segment_value,
    CASE promo_group
        WHEN 'none' THEN 1
        WHEN 'display_only' THEN 2
        WHEN 'mailer_only' THEN 3
        ELSE 4
    END;
