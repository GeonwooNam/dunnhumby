-- =============================================================
-- 04-2. 연관 카테고리 — 진열 상품과 무엇이 같이 팔리나
-- 목적: 교차구매가 무작위인지, 의미 있는 묶음인지 확인
-- 방법: 특별진열 장바구니(A) vs 대조(B)에서 각 '다른' 카테고리 출현율의 lift
--   ※ A 장바구니가 원래 조금 커서(카테고리 11 vs 10) baseline lift ≈ 1.1
--     → 1.1을 확실히 넘는 카테고리만 진짜 연관구매
-- 결과: 육류·가공육 / 식사 완성재 / 간식·음료 = '한 끼 장보기' 묶음 (lift 1.34~1.5)
-- =============================================================
WITH promo AS (
  SELECT PRODUCT_ID, STORE_ID, WEEK_NO,
    MAX(CASE WHEN display IN ('1','2','3','4','5','6','7','9') THEN 1 ELSE 0 END) AS disp_special
  FROM 'promo_candidates.parquet' GROUP BY 1,2,3
),
tx AS (
  SELECT t.household_key, t.BASKET_ID, t.STORE_ID, t.WEEK_NO,
         t.PRODUCT_ID, p.COMMODITY_DESC
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
btag AS (
  SELECT BASKET_ID, MAX(disp_special) AS grpA, MAX(is_candidate::INT) AS has_cand
  FROM lines GROUP BY BASKET_ID
),
cand_cats AS (SELECT DISTINCT COMMODITY_DESC FROM lines WHERE is_candidate),
n AS (
  SELECT COUNT(*) FILTER (grpA=1) AS nA, COUNT(*) FILTER (grpA=0) AS nB
  FROM btag WHERE has_cand=1
),
bc AS (
  SELECT DISTINCT l.BASKET_ID, l.COMMODITY_DESC, b.grpA
  FROM lines l JOIN btag b USING(BASKET_ID)
  WHERE b.has_cand=1
    AND l.COMMODITY_DESC NOT IN (SELECT COMMODITY_DESC FROM cand_cats)
),
cat AS (
  SELECT COMMODITY_DESC,
         COUNT(*) FILTER (grpA=1) AS inA,
         COUNT(*) FILTER (grpA=0) AS inB
  FROM bc GROUP BY COMMODITY_DESC
)
SELECT COMMODITY_DESC AS 연관카테고리,
  ROUND(100.0*inA/(SELECT nA FROM n),1) AS A_출현율,
  ROUND(100.0*inB/(SELECT nB FROM n),1) AS B_출현율,
  ROUND((1.0*inA/(SELECT nA FROM n))/(1.0*inB/(SELECT nB FROM n)),2) AS lift
FROM cat
WHERE inB >= 300
ORDER BY lift DESC
LIMIT 15;
