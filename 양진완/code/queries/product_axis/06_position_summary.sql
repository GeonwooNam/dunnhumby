-- 목적: 전단 위치와 특별 진열 위치별 트래픽 보정 관측 성과를 비교한다.
-- 입력: mart_product_store_week
-- 출력: mart_position_summary, mart_position_heatmap
-- 전단 위치 비교에서 쿠폰/무료증정 코드와 충돌 키는 제외한다.

CREATE OR REPLACE TABLE mart_position_summary AS
WITH position_rows AS (
    SELECT
        'mailer' AS promo_type,
        mailer_code AS position_code,
        weekly_sales,
        purchase_incidence,
        sales_per_visitor,
        buyer_penetration_rate,
        basket_share_rate,
        basket_count,
        buyer_count,
        PRODUCT_ID,
        STORE_ID
    FROM mart_product_store_week
    WHERE sold_weeks >= 8
      AND promo_code_conflict = 0
      AND panel_visitors >= 10
      AND mailer_offer_type = 'position'
      AND mailer_code IN ('A', 'C', 'D', 'F', 'H', 'L')
    UNION ALL
    SELECT
        'display',
        display_code,
        weekly_sales,
        purchase_incidence,
        sales_per_visitor,
        buyer_penetration_rate,
        basket_share_rate,
        basket_count,
        buyer_count,
        PRODUCT_ID,
        STORE_ID
    FROM mart_product_store_week
    WHERE sold_weeks >= 8
      AND promo_code_conflict = 0
      AND panel_visitors >= 10
      AND is_display = 1
      AND display_code IS NOT NULL
)
SELECT
    promo_type,
    position_code,
    COUNT(*) AS pair_weeks,
    COUNT(DISTINCT PRODUCT_ID) AS products,
    COUNT(DISTINCT STORE_ID) AS stores,
    COUNT(DISTINCT (PRODUCT_ID, STORE_ID)) AS product_store_pairs,
    AVG(weekly_sales) AS avg_weekly_sales,
    MEDIAN(weekly_sales) AS median_weekly_sales,
    AVG(purchase_incidence) AS sales_incidence_rate,
    AVG(sales_per_visitor) AS avg_sales_per_visitor,
    AVG(buyer_penetration_rate) AS avg_buyer_penetration_rate,
    AVG(basket_share_rate) AS avg_basket_share_rate,
    AVG(basket_count) AS avg_basket_count,
    AVG(buyer_count) AS avg_buyer_count,
    RANK() OVER (
        PARTITION BY promo_type ORDER BY AVG(sales_per_visitor) DESC
    ) AS traffic_adjusted_rank
FROM position_rows
GROUP BY 1, 2
ORDER BY promo_type, traffic_adjusted_rank, position_code;

CREATE OR REPLACE TABLE mart_position_heatmap AS
SELECT
    mailer_code,
    display_code,
    COUNT(*) AS pair_weeks,
    COUNT(DISTINCT PRODUCT_ID) AS products,
    COUNT(DISTINCT (PRODUCT_ID, STORE_ID)) AS product_store_pairs,
    AVG(weekly_sales) AS avg_weekly_sales,
    MEDIAN(weekly_sales) AS median_weekly_sales,
    AVG(purchase_incidence) AS sales_incidence_rate,
    AVG(sales_per_visitor) AS avg_sales_per_visitor,
    AVG(buyer_penetration_rate) AS avg_buyer_penetration_rate,
    AVG(basket_share_rate) AS avg_basket_share_rate,
    AVG(buyer_count) AS avg_buyer_count
FROM mart_product_store_week
WHERE sold_weeks >= 8
  AND panel_visitors >= 10
  AND promo_code_conflict = 0
  AND mailer_code IN ('A', 'C', 'D', 'F', 'H', 'L')
  AND is_display = 1
  AND display_code IN ('1', '2', '3', '4', '5', '6', '7', '9')
GROUP BY 1, 2
HAVING COUNT(*) >= 100
ORDER BY mailer_code, display_code;
