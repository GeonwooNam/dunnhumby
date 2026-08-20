-- 목적: 동일 상품-점포 내부에서 트래픽 보정 KPI를 프로모션 상태별로 비교한다.
-- 입력: mart_product_store_week
-- 출력: work_pair_group_means, mart_within_pair_summary
-- 점포-주 방문 패널 10명 이상인 주만 사용한다.

CREATE OR REPLACE TABLE work_pair_group_means AS
SELECT
    PRODUCT_ID,
    STORE_ID,
    promo_group,
    COUNT(*) AS observed_weeks,
    AVG(weekly_sales) AS avg_weekly_sales,
    AVG(purchase_incidence) AS purchase_incidence_rate,
    AVG(buyer_penetration_rate) AS avg_buyer_penetration_rate,
    AVG(sales_per_visitor) AS avg_sales_per_visitor,
    AVG(basket_share_rate) AS avg_basket_share_rate,
    AVG(store_sales_share_rate) AS avg_store_sales_share_rate,
    AVG(category_sales_share_rate) AS avg_category_sales_share_rate
FROM mart_product_store_week
WHERE sold_weeks >= 8
  AND panel_visitors >= 10
  AND promo_group IN ('none', 'display_only', 'mailer_only', 'both')
GROUP BY 1, 2, 3;

CREATE OR REPLACE TABLE mart_within_pair_summary AS
WITH pair_pivot AS (
    SELECT
        PRODUCT_ID,
        STORE_ID,
        MAX(avg_weekly_sales) FILTER (WHERE promo_group = 'none') AS none_sales,
        MAX(avg_weekly_sales) FILTER (WHERE promo_group = 'display_only') AS display_sales,
        MAX(avg_weekly_sales) FILTER (WHERE promo_group = 'mailer_only') AS mailer_sales,
        MAX(avg_weekly_sales) FILTER (WHERE promo_group = 'both') AS both_sales,
        MAX(avg_sales_per_visitor) FILTER (WHERE promo_group = 'none') AS none_spv,
        MAX(avg_sales_per_visitor) FILTER (WHERE promo_group = 'display_only') AS display_spv,
        MAX(avg_sales_per_visitor) FILTER (WHERE promo_group = 'mailer_only') AS mailer_spv,
        MAX(avg_sales_per_visitor) FILTER (WHERE promo_group = 'both') AS both_spv,
        MAX(avg_buyer_penetration_rate) FILTER (WHERE promo_group = 'none') AS none_bpr,
        MAX(avg_buyer_penetration_rate) FILTER (WHERE promo_group = 'display_only') AS display_bpr,
        MAX(avg_buyer_penetration_rate) FILTER (WHERE promo_group = 'mailer_only') AS mailer_bpr,
        MAX(avg_buyer_penetration_rate) FILTER (WHERE promo_group = 'both') AS both_bpr,
        MAX(avg_basket_share_rate) FILTER (WHERE promo_group = 'none') AS none_basket_share,
        MAX(avg_basket_share_rate) FILTER (WHERE promo_group = 'display_only') AS display_basket_share,
        MAX(avg_basket_share_rate) FILTER (WHERE promo_group = 'mailer_only') AS mailer_basket_share,
        MAX(avg_basket_share_rate) FILTER (WHERE promo_group = 'both') AS both_basket_share,
        MAX(observed_weeks) FILTER (WHERE promo_group = 'none') AS none_weeks,
        MAX(observed_weeks) FILTER (WHERE promo_group = 'display_only') AS display_weeks,
        MAX(observed_weeks) FILTER (WHERE promo_group = 'mailer_only') AS mailer_weeks,
        MAX(observed_weeks) FILTER (WHERE promo_group = 'both') AS both_weeks
    FROM work_pair_group_means
    GROUP BY 1, 2
),
comparisons AS (
    SELECT PRODUCT_ID, STORE_ID, 'display_only_vs_none' AS comparison,
        none_sales AS reference_sales, display_sales AS comparison_sales,
        none_spv AS reference_spv, display_spv AS comparison_spv,
        none_bpr AS reference_bpr, display_bpr AS comparison_bpr,
        none_basket_share AS reference_basket_share,
        display_basket_share AS comparison_basket_share,
        none_weeks AS reference_weeks, display_weeks AS comparison_weeks
    FROM pair_pivot WHERE none_spv IS NOT NULL AND display_spv IS NOT NULL
    UNION ALL
    SELECT PRODUCT_ID, STORE_ID, 'mailer_only_vs_none',
        none_sales, mailer_sales, none_spv, mailer_spv, none_bpr, mailer_bpr,
        none_basket_share, mailer_basket_share, none_weeks, mailer_weeks
    FROM pair_pivot WHERE none_spv IS NOT NULL AND mailer_spv IS NOT NULL
    UNION ALL
    SELECT PRODUCT_ID, STORE_ID, 'both_vs_none',
        none_sales, both_sales, none_spv, both_spv, none_bpr, both_bpr,
        none_basket_share, both_basket_share, none_weeks, both_weeks
    FROM pair_pivot WHERE none_spv IS NOT NULL AND both_spv IS NOT NULL
    UNION ALL
    SELECT PRODUCT_ID, STORE_ID, 'both_increment_over_additive',
        mailer_sales + display_sales - none_sales, both_sales,
        mailer_spv + display_spv - none_spv, both_spv,
        mailer_bpr + display_bpr - none_bpr, both_bpr,
        mailer_basket_share + display_basket_share - none_basket_share,
        both_basket_share,
        mailer_weeks + display_weeks, both_weeks
    FROM pair_pivot
    WHERE none_spv IS NOT NULL AND display_spv IS NOT NULL
      AND mailer_spv IS NOT NULL AND both_spv IS NOT NULL
)
SELECT
    comparison,
    COUNT(*) AS product_store_pairs,
    AVG(reference_sales) AS avg_reference_sales,
    AVG(comparison_sales) AS avg_comparison_sales,
    100.0 * (AVG(comparison_sales) / NULLIF(AVG(reference_sales), 0) - 1)
        AS raw_sales_lift_pct,
    AVG(reference_spv) AS avg_reference_sales_per_visitor,
    AVG(comparison_spv) AS avg_comparison_sales_per_visitor,
    100.0 * (AVG(comparison_spv) / NULLIF(AVG(reference_spv), 0) - 1)
        AS sales_per_visitor_lift_pct,
    MEDIAN(comparison_spv - reference_spv)
        AS median_sales_per_visitor_difference,
    100.0 * AVG(CASE WHEN comparison_spv > reference_spv THEN 1.0 ELSE 0.0 END)
        AS pairs_with_positive_spv_difference_pct,
    100.0 * (AVG(comparison_bpr) - AVG(reference_bpr))
        AS buyer_penetration_difference_pp,
    100.0 * (AVG(comparison_basket_share) - AVG(reference_basket_share))
        AS basket_share_difference_pp,
    SUM(reference_weeks) AS reference_weeks,
    SUM(comparison_weeks) AS comparison_weeks
FROM comparisons
GROUP BY comparison
ORDER BY CASE comparison
    WHEN 'display_only_vs_none' THEN 1
    WHEN 'mailer_only_vs_none' THEN 2
    WHEN 'both_vs_none' THEN 3
    ELSE 4
END;
