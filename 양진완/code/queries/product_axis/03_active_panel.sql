-- 목적: 판매 활성구간을 전개하고 판매성과와 프로모션 상태를 결합한다.
-- 입력: 판매 집계, 점포-주 패널 트래픽, 프로모션 정제, 상품 마스터
-- 출력: work_active_pairs, mart_product_store_week
-- 최소 4개 판매주 쌍을 저장하고 주 분석에서는 sold_weeks >= 8을 사용한다.

CREATE OR REPLACE TABLE work_active_pairs AS
SELECT
    PRODUCT_ID,
    STORE_ID,
    MIN(WEEK_NO) AS first_week,
    MAX(WEEK_NO) AS last_week,
    COUNT(*) AS sold_weeks
FROM work_product_store_week_sales
GROUP BY 1, 2
HAVING COUNT(*) >= 4;

CREATE OR REPLACE TABLE mart_product_store_week AS
WITH active_grid AS (
    SELECT
        a.PRODUCT_ID,
        a.STORE_ID,
        w.WEEK_NO,
        a.first_week,
        a.last_week,
        a.sold_weeks
    FROM work_active_pairs AS a,
    UNNEST(range(a.first_week, a.last_week + 1)) AS w(WEEK_NO)
),
panel_base AS (
    SELECT
        g.PRODUCT_ID,
        g.STORE_ID,
        g.WEEK_NO,
        g.first_week,
        g.last_week,
        g.sold_weeks,
        COALESCE(s.weekly_sales, 0.0) AS weekly_sales,
        COALESCE(s.positive_sales, 0.0) AS positive_sales,
        COALESCE(s.weekly_quantity, 0) AS weekly_quantity,
        COALESCE(s.basket_count, 0) AS basket_count,
        COALESCE(s.buyer_count, 0) AS buyer_count,
        COALESCE(s.purchase_incidence, 0) AS purchase_incidence,
        COALESCE(s.retail_discount_amount, 0.0) AS retail_discount_amount,
        COALESCE(sw.panel_visitors, 0) AS panel_visitors,
        COALESCE(sw.store_week_baskets, 0) AS store_week_baskets,
        COALESCE(sw.panel_store_sales, 0.0) AS panel_store_sales,
        COALESCE(cw.panel_category_sales, 0.0) AS panel_category_sales,
        COALESCE(p.is_mailer, 0) AS is_mailer,
        COALESCE(p.is_display, 0) AS is_display,
        COALESCE(p.is_both, 0) AS is_both,
        COALESCE(p.promotion_record_present, 0) AS promotion_record_present,
        COALESCE(p.is_explicit_none, 0) AS is_explicit_none,
        COALESCE(p.promo_group, 'unobserved') AS promo_group,
        p.mailer_code,
        p.display_code,
        COALESCE(p.mailer_offer_type, 'none') AS mailer_offer_type,
        COALESCE(p.promo_code_conflict, 0) AS promo_code_conflict
    FROM active_grid AS g
    LEFT JOIN work_product_store_week_sales AS s
        USING (PRODUCT_ID, STORE_ID, WEEK_NO)
    LEFT JOIN work_store_week_context AS sw
        USING (STORE_ID, WEEK_NO)
    LEFT JOIN work_promotion_clean AS p
        USING (PRODUCT_ID, STORE_ID, WEEK_NO)
    LEFT JOIN source.product AS pr
        USING (PRODUCT_ID)
    LEFT JOIN work_category_store_week_sales AS cw
        ON cw.STORE_ID = g.STORE_ID
       AND cw.WEEK_NO = g.WEEK_NO
       AND cw.COMMODITY_DESC = pr.COMMODITY_DESC
)
SELECT
    *,
    CASE
        WHEN panel_visitors > 0 THEN buyer_count::DOUBLE / panel_visitors
    END AS buyer_penetration_rate,
    CASE
        WHEN panel_visitors > 0 THEN weekly_sales / panel_visitors
    END AS sales_per_visitor,
    CASE
        WHEN store_week_baskets > 0 THEN basket_count::DOUBLE / store_week_baskets
    END AS basket_share_rate,
    CASE
        WHEN panel_store_sales > 0 THEN weekly_sales / panel_store_sales
    END AS store_sales_share_rate,
    CASE
        WHEN panel_category_sales > 0 THEN weekly_sales / panel_category_sales
    END AS category_sales_share_rate,
    LAG(purchase_incidence) OVER (
        PARTITION BY PRODUCT_ID, STORE_ID ORDER BY WEEK_NO
    ) AS sold_previous_week,
    LEAD(purchase_incidence) OVER (
        PARTITION BY PRODUCT_ID, STORE_ID ORDER BY WEEK_NO
    ) AS sold_next_week
FROM panel_base;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mart_product_store_week_key
ON mart_product_store_week (PRODUCT_ID, STORE_ID, WEEK_NO);
