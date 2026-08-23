-- =============================================================
-- 03-4. 쿠폰 증분 매출 — DiD(이중차분) + 사전지출 5분위 층화
-- 목적: "쿠폰 받은 가구가 진짜 매출을 늘렸나" (킥오프 Sub2 핵심 질문)
-- 방법: 전반(W17~58)/후반(W59~101) 분할, treatment=후반 캠페인 타겟,
--       전반 지출로 5분위 층화 후 (후반-전반) 변화량 차이 비교
-- 결과: 가중평균 +약7%지만 매출 최대 5층에서 역전(평균회귀 오염) → 작고 불확실
--       (파이썬 정밀 DiD +1.6~5.7%, 플라시보 40% 재현과 일치)
-- ⚠️ 반쪽 분할이라 평균회귀에 취약 — 정밀 검증은 python/06_incremental.py
-- =============================================================
WITH tx AS (
  SELECT t.household_key, t.DAY, t.WEEK_NO, t.SALES_VALUE
  FROM read_csv_auto('transaction_data.csv') t
  JOIN read_csv_auto('product.csv') p USING (PRODUCT_ID)
  WHERE t.WEEK_NO BETWEEN 17 AND 101
    AND p.DEPARTMENT NOT IN ('KIOSK-GAS','MISC SALES TRAN')
),
half AS (
  SELECT household_key,
    SUM(SALES_VALUE) FILTER (WHERE WEEK_NO <= 58)               AS pre_spend,
    SUM(SALES_VALUE) FILTER (WHERE WEEK_NO <= 58) / 42.0        AS pre_wk,
    COALESCE(SUM(SALES_VALUE) FILTER (WHERE WEEK_NO >= 59),0)/43.0 AS post_wk
  FROM tx GROUP BY household_key
),
day59 AS (SELECT MIN(DAY) AS d FROM tx WHERE WEEK_NO = 59),
treat AS (
  SELECT DISTINCT ct.household_key
  FROM read_csv_auto('campaign_table.csv') ct
  JOIN read_csv_auto('campaign_desc.csv') cd USING (CAMPAIGN)
  WHERE cd.START_DAY >= (SELECT d FROM day59)
),
panel AS (
  SELECT h.pre_wk, h.post_wk - h.pre_wk AS delta,
         (h.household_key IN (SELECT household_key FROM treat)) AS targeted,
         NTILE(5) OVER (ORDER BY h.pre_spend) AS tier
  FROM half h
)
SELECT
  tier,
  COUNT(*) FILTER (targeted)                          AS 타겟_n,
  ROUND(AVG(delta) FILTER (targeted),3)               AS 타겟_변화,
  ROUND(AVG(delta) FILTER (NOT targeted),3)           AS 대조_변화,
  ROUND(AVG(delta) FILTER (targeted)
      - AVG(delta) FILTER (NOT targeted),3)           AS DiD
FROM panel
GROUP BY tier ORDER BY tier;
