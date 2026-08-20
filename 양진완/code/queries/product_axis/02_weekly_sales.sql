-- 목적: 거래 행을 상품-점포-주 단위로 집계하고 패널 트래픽 분모를 만든다.
-- 입력: source.transaction_data, source.causal_data
-- 출력: work_store_week_context, work_week_context,
--       work_product_week_sales, work_category_store_week_sales,
--       work_product_store_week_sales
-- 범위: causal_data와 겹치는 9~101주 및 115개 점포

CREATE OR REPLACE TABLE work_store_week_context AS
WITH causal_stores AS (
    SELECT DISTINCT STORE_ID
    FROM source.causal_data
)
SELECT
    t.STORE_ID,
    t.WEEK_NO,
    COUNT(DISTINCT t.household_key) AS panel_visitors,
    COUNT(DISTINCT t.BASKET_ID) AS store_week_baskets,
    SUM(t.SALES_VALUE) AS panel_store_sales,
    SUM(CASE WHEN t.SALES_VALUE > 0 THEN t.SALES_VALUE ELSE 0 END)
        AS positive_panel_store_sales
FROM source.transaction_data AS t
INNER JOIN causal_stores AS s USING (STORE_ID)
WHERE t.WEEK_NO BETWEEN 9 AND 101
  AND (t.QUANTITY > 0 OR t.SALES_VALUE > 0)
GROUP BY 1, 2;

CREATE UNIQUE INDEX IF NOT EXISTS idx_work_store_week_context
ON work_store_week_context (STORE_ID, WEEK_NO);

CREATE OR REPLACE TABLE work_week_context AS
WITH causal_stores AS (
    SELECT DISTINCT STORE_ID
    FROM source.causal_data
)
SELECT
    t.WEEK_NO,
    COUNT(DISTINCT t.household_key) AS panel_week_visitors,
    COUNT(DISTINCT t.BASKET_ID) AS panel_week_baskets,
    SUM(t.SALES_VALUE) AS panel_week_sales
FROM source.transaction_data AS t
INNER JOIN causal_stores AS s USING (STORE_ID)
WHERE t.WEEK_NO BETWEEN 9 AND 101
  AND (t.QUANTITY > 0 OR t.SALES_VALUE > 0)
GROUP BY 1;

CREATE UNIQUE INDEX IF NOT EXISTS idx_work_week_context
ON work_week_context (WEEK_NO);

CREATE OR REPLACE TABLE work_product_week_sales AS
WITH causal_stores AS (
    SELECT DISTINCT STORE_ID
    FROM source.causal_data
)
SELECT
    t.PRODUCT_ID,
    t.WEEK_NO,
    SUM(t.SALES_VALUE) AS weekly_sales,
    COUNT(DISTINCT t.household_key) AS buyer_count,
    COUNT(DISTINCT t.BASKET_ID) AS basket_count,
    SUM(t.QUANTITY) AS weekly_quantity
FROM source.transaction_data AS t
INNER JOIN causal_stores AS s USING (STORE_ID)
WHERE t.WEEK_NO BETWEEN 9 AND 101
  AND (t.QUANTITY > 0 OR t.SALES_VALUE > 0)
GROUP BY 1, 2;

CREATE UNIQUE INDEX IF NOT EXISTS idx_work_product_week_sales
ON work_product_week_sales (PRODUCT_ID, WEEK_NO);

CREATE OR REPLACE TABLE work_category_store_week_sales AS
WITH causal_stores AS (
    SELECT DISTINCT STORE_ID
    FROM source.causal_data
)
SELECT
    t.STORE_ID,
    t.WEEK_NO,
    p.COMMODITY_DESC,
    SUM(t.SALES_VALUE) AS panel_category_sales,
    COUNT(DISTINCT t.BASKET_ID) AS category_baskets
FROM source.transaction_data AS t
INNER JOIN causal_stores AS s USING (STORE_ID)
INNER JOIN source.product AS p USING (PRODUCT_ID)
WHERE t.WEEK_NO BETWEEN 9 AND 101
  AND (t.QUANTITY > 0 OR t.SALES_VALUE > 0)
GROUP BY 1, 2, 3;

CREATE INDEX IF NOT EXISTS idx_work_category_store_week
ON work_category_store_week_sales (STORE_ID, WEEK_NO, COMMODITY_DESC);

CREATE OR REPLACE TABLE work_product_store_week_sales AS
WITH causal_stores AS (
    SELECT DISTINCT STORE_ID
    FROM source.causal_data
)
SELECT
    t.PRODUCT_ID,
    t.STORE_ID,
    t.WEEK_NO,
    SUM(t.SALES_VALUE) AS weekly_sales,
    SUM(CASE WHEN t.SALES_VALUE > 0 THEN t.SALES_VALUE ELSE 0 END)
        AS positive_sales,
    SUM(t.QUANTITY) AS weekly_quantity,
    COUNT(DISTINCT t.BASKET_ID) AS basket_count,
    COUNT(DISTINCT t.household_key) AS buyer_count,
    1 AS purchase_incidence,
    -SUM(t.RETAIL_DISC) AS retail_discount_amount,
    COUNT(*) AS transaction_row_count,
    COUNT(*) FILTER (
        WHERE t.SALES_VALUE = 0 OR t.QUANTITY = 0
    ) AS zero_component_row_count
FROM source.transaction_data AS t
INNER JOIN causal_stores AS s USING (STORE_ID)
WHERE t.WEEK_NO BETWEEN 9 AND 101
  AND (t.QUANTITY > 0 OR t.SALES_VALUE > 0)
GROUP BY 1, 2, 3;

CREATE UNIQUE INDEX IF NOT EXISTS idx_work_weekly_sales_key
ON work_product_store_week_sales (PRODUCT_ID, STORE_ID, WEEK_NO);
