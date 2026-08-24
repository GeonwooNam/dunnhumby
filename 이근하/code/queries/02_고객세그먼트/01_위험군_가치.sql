-- =============================================================
-- 02-1. 위험군의 가치 (위험군 vs 정상군)
-- 목적: 35일+ 위험군이 매출에서 차지하는 비중 → 방어 가치 판단
-- 결과: 가구 17%인데 매출 6% → 떠나는 사람 = 원래 조금 쓰던 사람
--       (단 평균 934 > 중앙값 501 → 위험군 안에 소수 큰손 섞임 → 세분화 필요)
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
)
SELECT
  CASE WHEN recency >= 35 THEN '위험군(35일+)' ELSE '정상군' END AS segment,
  COUNT(*)                                              AS households,
  ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER (),1)         AS pct_households,
  ROUND(SUM(total_spend))                               AS total_spend,
  ROUND(100.0*SUM(total_spend)/SUM(SUM(total_spend)) OVER (),1) AS pct_spend,
  ROUND(AVG(total_spend))                               AS avg_spend,
  ROUND(MEDIAN(total_spend))                            AS median_spend
FROM hh
GROUP BY (recency >= 35)
ORDER BY segment;
