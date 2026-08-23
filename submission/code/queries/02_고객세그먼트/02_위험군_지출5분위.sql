-- =============================================================
-- 02-2. 위험군 세분화 — 지출 5분위
-- 목적: 위험군을 가치로 쪼개 "구할 가치 있는" 층 식별
-- 결과: 위험군 상위 20%(85가구)가 위험군 매출의 59.4% 차지
--       (하위 절반은 다 합쳐도 7% → 전면 타겟팅은 낭비)
-- =============================================================
WITH tx AS (
  SELECT t.household_key, t.DAY, t.SALES_VALUE
  FROM read_csv_auto('transaction_data.csv') t
  JOIN read_csv_auto('product.csv') p USING (PRODUCT_ID)
  WHERE t.WEEK_NO BETWEEN 17 AND 101
    AND p.DEPARTMENT NOT IN ('KIOSK-GAS','MISC SALES TRAN')
),
hh AS (
  SELECT household_key, SUM(SALES_VALUE) AS total_spend,
         (SELECT MAX(DAY) FROM tx) - MAX(DAY) AS recency
  FROM tx GROUP BY household_key
),
risk AS (
  SELECT household_key, total_spend,
         NTILE(5) OVER (ORDER BY total_spend) AS spend_tier
  FROM hh WHERE recency >= 35
)
SELECT
  spend_tier,
  COUNT(*)                                  AS households,
  ROUND(MIN(total_spend))                    AS min_spend,
  ROUND(MAX(total_spend))                    AS max_spend,
  ROUND(SUM(total_spend))                     AS tier_spend,
  ROUND(100.0*SUM(total_spend)/SUM(SUM(total_spend)) OVER (),1) AS pct_of_risk_spend
FROM risk
GROUP BY spend_tier
ORDER BY spend_tier;
