-- 목적: 전단을 점포 단위가 아닌 상품-주 단위로 집계해 기술 성과를 비교한다.
-- 입력: work_product_week_sales, work_week_context, work_promotion_clean
-- 출력: mart_mailer_product_week, mart_mailer_product_week_summary,
--       mart_mailer_within_product_summary
-- 전단은 같은 상품-주에서 점포별 변동이 거의 없으므로 115개 점포를 합친다.

CREATE OR REPLACE TABLE work_product_week_promotion AS
SELECT
    PRODUCT_ID,
    WEEK_NO,
    MAX(is_mailer) AS is_mailer,
    MAX(is_display) AS any_display,
    MAX(promotion_record_present) AS promotion_record_present,
    MAX(is_explicit_none) AS has_explicit_none,
    COUNT(DISTINCT STORE_ID) AS promotion_record_stores,
    COUNT(DISTINCT STORE_ID) FILTER (WHERE is_mailer = 1)
        AS mailer_record_stores,
    COUNT(DISTINCT STORE_ID) FILTER (WHERE is_display = 1)
        AS display_record_stores
FROM work_promotion_clean
WHERE promo_code_conflict = 0
GROUP BY 1, 2;

CREATE OR REPLACE TABLE work_active_products AS
SELECT
    PRODUCT_ID,
    MIN(WEEK_NO) AS first_week,
    MAX(WEEK_NO) AS last_week,
    COUNT(*) AS sold_weeks
FROM work_product_week_sales
GROUP BY 1
HAVING COUNT(*) >= 8;

CREATE OR REPLACE TABLE mart_mailer_product_week AS
WITH product_week_grid AS (
    SELECT
        a.PRODUCT_ID,
        w.WEEK_NO,
        a.first_week,
        a.last_week,
        a.sold_weeks
    FROM work_active_products AS a,
    UNNEST(range(a.first_week, a.last_week + 1)) AS w(WEEK_NO)
)
SELECT
    g.PRODUCT_ID,
    g.WEEK_NO,
    g.first_week,
    g.last_week,
    g.sold_weeks,
    COALESCE(s.weekly_sales, 0.0) AS weekly_sales,
    COALESCE(s.buyer_count, 0) AS buyer_count,
    COALESCE(s.basket_count, 0) AS basket_count,
    COALESCE(s.weekly_quantity, 0) AS weekly_quantity,
    CASE WHEN s.PRODUCT_ID IS NULL THEN 0 ELSE 1 END AS purchase_incidence,
    w.panel_week_visitors,
    w.panel_week_baskets,
    w.panel_week_sales,
    COALESCE(p.is_mailer, 0) AS is_mailer,
    COALESCE(p.any_display, 0) AS any_display,
    COALESCE(p.promotion_record_present, 0) AS promotion_record_present,
    COALESCE(p.has_explicit_none, 0) AS has_explicit_none,
    COALESCE(p.promotion_record_stores, 0) AS promotion_record_stores,
    COALESCE(p.mailer_record_stores, 0) AS mailer_record_stores,
    COALESCE(p.display_record_stores, 0) AS display_record_stores,
    CASE
        WHEN w.panel_week_visitors > 0
        THEN COALESCE(s.buyer_count, 0)::DOUBLE / w.panel_week_visitors
    END AS buyer_penetration_rate,
    CASE
        WHEN w.panel_week_visitors > 0
        THEN COALESCE(s.weekly_sales, 0.0) / w.panel_week_visitors
    END AS sales_per_visitor,
    CASE
        WHEN w.panel_week_baskets > 0
        THEN COALESCE(s.basket_count, 0)::DOUBLE / w.panel_week_baskets
    END AS basket_share_rate,
    CASE
        WHEN w.panel_week_sales > 0
        THEN COALESCE(s.weekly_sales, 0.0) / w.panel_week_sales
    END AS weekly_sales_share_rate
FROM product_week_grid AS g
INNER JOIN work_week_context AS w USING (WEEK_NO)
LEFT JOIN work_product_week_sales AS s USING (PRODUCT_ID, WEEK_NO)
LEFT JOIN work_product_week_promotion AS p USING (PRODUCT_ID, WEEK_NO);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mart_mailer_product_week
ON mart_mailer_product_week (PRODUCT_ID, WEEK_NO);

CREATE OR REPLACE TABLE mart_mailer_product_week_summary AS
WITH sampled AS (
    SELECT 'all_product_weeks' AS sample_definition, *
    FROM mart_mailer_product_week
    WHERE promotion_record_present = 1
    UNION ALL
    SELECT 'no_display_any_store', *
    FROM mart_mailer_product_week
    WHERE promotion_record_present = 1 AND any_display = 0
),
summary AS (
    SELECT
        sample_definition,
        CASE WHEN is_mailer = 1 THEN 'mailer' ELSE 'no_mailer' END
            AS mailer_group,
        COUNT(*) AS product_weeks,
        COUNT(DISTINCT PRODUCT_ID) AS products,
        AVG(panel_week_visitors) AS avg_week_visitors,
        AVG(weekly_sales) AS avg_weekly_sales,
        AVG(purchase_incidence) AS purchase_incidence_rate,
        AVG(buyer_penetration_rate) AS avg_buyer_penetration_rate,
        AVG(sales_per_visitor) AS avg_sales_per_visitor,
        AVG(basket_share_rate) AS avg_basket_share_rate,
        AVG(weekly_sales_share_rate) AS avg_weekly_sales_share_rate
    FROM sampled
    GROUP BY 1, 2
),
with_baseline AS (
    SELECT
        *,
        MAX(avg_weekly_sales) FILTER (WHERE mailer_group = 'no_mailer')
            OVER (PARTITION BY sample_definition) AS no_mailer_avg_sales,
        MAX(avg_buyer_penetration_rate) FILTER (WHERE mailer_group = 'no_mailer')
            OVER (PARTITION BY sample_definition) AS no_mailer_buyer_penetration,
        MAX(avg_sales_per_visitor) FILTER (WHERE mailer_group = 'no_mailer')
            OVER (PARTITION BY sample_definition) AS no_mailer_sales_per_visitor,
        MAX(avg_basket_share_rate) FILTER (WHERE mailer_group = 'no_mailer')
            OVER (PARTITION BY sample_definition) AS no_mailer_basket_share,
        MAX(avg_weekly_sales_share_rate) FILTER (WHERE mailer_group = 'no_mailer')
            OVER (PARTITION BY sample_definition) AS no_mailer_sales_share
    FROM summary
)
SELECT
    *,
    100.0 * (avg_weekly_sales / NULLIF(no_mailer_avg_sales, 0) - 1)
        AS raw_sales_lift_pct,
    100.0 * (
        avg_buyer_penetration_rate / NULLIF(no_mailer_buyer_penetration, 0) - 1
    ) AS buyer_penetration_lift_pct,
    100.0 * (
        avg_sales_per_visitor / NULLIF(no_mailer_sales_per_visitor, 0) - 1
    ) AS sales_per_visitor_lift_pct,
    100.0 * (
        avg_basket_share_rate / NULLIF(no_mailer_basket_share, 0) - 1
    ) AS basket_share_lift_pct,
    100.0 * (
        avg_weekly_sales_share_rate / NULLIF(no_mailer_sales_share, 0) - 1
    ) AS weekly_sales_share_lift_pct
FROM with_baseline
ORDER BY sample_definition,
    CASE mailer_group WHEN 'no_mailer' THEN 1 ELSE 2 END;

CREATE OR REPLACE TABLE mart_mailer_within_product_summary AS
WITH sampled AS (
    SELECT 'all_product_weeks' AS sample_definition, *
    FROM mart_mailer_product_week
    WHERE promotion_record_present = 1
    UNION ALL
    SELECT 'no_display_any_store', *
    FROM mart_mailer_product_week
    WHERE promotion_record_present = 1 AND any_display = 0
),
product_status_means AS (
    SELECT
        sample_definition,
        PRODUCT_ID,
        is_mailer,
        COUNT(*) AS observed_weeks,
        AVG(weekly_sales) AS avg_weekly_sales,
        AVG(sales_per_visitor) AS avg_sales_per_visitor,
        AVG(buyer_penetration_rate) AS avg_buyer_penetration_rate,
        AVG(basket_share_rate) AS avg_basket_share_rate,
        AVG(weekly_sales_share_rate) AS avg_weekly_sales_share_rate
    FROM sampled
    GROUP BY 1, 2, 3
),
product_pivot AS (
    SELECT
        sample_definition,
        PRODUCT_ID,
        MAX(avg_weekly_sales) FILTER (WHERE is_mailer = 0) AS no_mailer_sales,
        MAX(avg_weekly_sales) FILTER (WHERE is_mailer = 1) AS mailer_sales,
        MAX(avg_sales_per_visitor) FILTER (WHERE is_mailer = 0) AS no_mailer_spv,
        MAX(avg_sales_per_visitor) FILTER (WHERE is_mailer = 1) AS mailer_spv,
        MAX(avg_buyer_penetration_rate) FILTER (WHERE is_mailer = 0)
            AS no_mailer_bpr,
        MAX(avg_buyer_penetration_rate) FILTER (WHERE is_mailer = 1)
            AS mailer_bpr,
        MAX(avg_basket_share_rate) FILTER (WHERE is_mailer = 0)
            AS no_mailer_basket_share,
        MAX(avg_basket_share_rate) FILTER (WHERE is_mailer = 1)
            AS mailer_basket_share,
        MAX(avg_weekly_sales_share_rate) FILTER (WHERE is_mailer = 0)
            AS no_mailer_sales_share,
        MAX(avg_weekly_sales_share_rate) FILTER (WHERE is_mailer = 1)
            AS mailer_sales_share,
        MAX(observed_weeks) FILTER (WHERE is_mailer = 0) AS no_mailer_weeks,
        MAX(observed_weeks) FILTER (WHERE is_mailer = 1) AS mailer_weeks
    FROM product_status_means
    GROUP BY 1, 2
)
SELECT
    sample_definition,
    COUNT(*) AS products,
    AVG(no_mailer_sales) AS avg_no_mailer_sales,
    AVG(mailer_sales) AS avg_mailer_sales,
    100.0 * (AVG(mailer_sales) / NULLIF(AVG(no_mailer_sales), 0) - 1)
        AS raw_sales_lift_pct,
    AVG(no_mailer_spv) AS avg_no_mailer_sales_per_visitor,
    AVG(mailer_spv) AS avg_mailer_sales_per_visitor,
    100.0 * (AVG(mailer_spv) / NULLIF(AVG(no_mailer_spv), 0) - 1)
        AS sales_per_visitor_lift_pct,
    100.0 * AVG(CASE WHEN mailer_spv > no_mailer_spv THEN 1.0 ELSE 0.0 END)
        AS products_with_positive_spv_difference_pct,
    100.0 * (AVG(mailer_bpr) - AVG(no_mailer_bpr))
        AS buyer_penetration_difference_pp,
    100.0 * (AVG(mailer_basket_share) - AVG(no_mailer_basket_share))
        AS basket_share_difference_pp,
    100.0 * (AVG(mailer_sales_share) - AVG(no_mailer_sales_share))
        AS weekly_sales_share_difference_pp,
    SUM(no_mailer_weeks) AS no_mailer_weeks,
    SUM(mailer_weeks) AS mailer_weeks
FROM product_pivot
WHERE no_mailer_spv IS NOT NULL AND mailer_spv IS NOT NULL
GROUP BY sample_definition
ORDER BY sample_definition;
