-- =============================================================
-- 04-1. 교차구매 — 진열은 장바구니 전체를 키우는가
-- 목적: 진열된 상품 옆에서 다른 상품도 같이 샀나 (킥오프 Sub3)
-- 방법: 후보 상품이 담긴 장바구니를, 그 상품이 특별 진열(display 1~9)된 경우(A)
--       vs 아닌 경우(B)로 나눠 '그 상품을 뺀 나머지 지출' 비교
--   ※ display 코드북(팀 공통): 0,A = 특별진열 아님 / 1~9 = 특별진열
--     (mailer 'A'는 전단 내부면이라 효과 낮음 → OR 이진화하면 신호가 사라짐)
-- 결과: 나머지 지출 +25%, 총액 +28% → 그 상품만이 아니라 같이 다른 것도 삼
-- 입력: output/tables/promo_candidates.parquet (36M행 causal_data 압축본)
-- =============================================================
WITH promo AS (
  SELECT PRODUCT_ID, STORE_ID, WEEK_NO,
         MAX(CASE WHEN display IN ('1','2','3','4','5','6','7','9')
                  THEN 1 ELSE 0 END) AS disp_special
  FROM 'promo_candidates.parquet'
  GROUP BY 1,2,3
),
tx AS (
  SELECT t.household_key, t.BASKET_ID, t.STORE_ID, t.WEEK_NO,
         t.PRODUCT_ID, t.SALES_VALUE, p.COMMODITY_DESC
  FROM read_csv_auto('transaction_data.csv') t
  JOIN read_csv_auto('product.csv') p USING (PRODUCT_ID)
  WHERE t.WEEK_NO BETWEEN 17 AND 101
    AND p.DEPARTMENT NOT IN ('KIOSK-GAS','MISC SALES TRAN')
),
lines AS (
  SELECT tx.*, (pr.PRODUCT_ID IS NOT NULL) AS is_candidate,
         COALESCE(pr.disp_special,0) AS disp_special
  FROM tx LEFT JOIN promo pr
    ON pr.PRODUCT_ID=tx.PRODUCT_ID AND pr.STORE_ID=tx.STORE_ID AND pr.WEEK_NO=tx.WEEK_NO
),
basket AS (
  SELECT BASKET_ID,
         MAX(disp_special)                          AS any_special,
         MAX(is_candidate::INT)                      AS has_candidate,
         SUM(SALES_VALUE)                            AS total,
         SUM(SALES_VALUE) FILTER (WHERE is_candidate) AS cand_spend,
         COUNT(DISTINCT COMMODITY_DESC)             AS n_cat
  FROM lines GROUP BY BASKET_ID
)
SELECT
  CASE WHEN any_special=1 THEN 'A) 특별진열 노출' ELSE 'B) 대조(진열 없음)' END AS grp,
  COUNT(*)                              AS 장바구니수,
  ROUND(MEDIAN(total),2)               AS 총액_중앙,
  ROUND(MEDIAN(total - cand_spend),2)  AS 후보외지출_중앙,
  ROUND(MEDIAN(n_cat),1)               AS 카테고리수_중앙
FROM basket
WHERE has_candidate=1
GROUP BY grp ORDER BY grp;
