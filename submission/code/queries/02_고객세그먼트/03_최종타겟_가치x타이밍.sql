-- =============================================================
-- 02-3. 최종 타겟 세분화 — 가치 × 타이밍 (2×2)
-- 목적: 위험군 상위 지출층을 이탈초기/이미이탈로 다시 나눠 실행 대상 확정
-- 결과: 고가치 × 이탈초기 = 50가구 (평소 방문 66회·지출 2,833)
--       → 진짜 단골이 막 끊기기 시작, 아직 골든타임 = 최종 타겟
-- =============================================================
WITH tx AS (
  SELECT t.household_key, t.DAY, t.SALES_VALUE
  FROM read_csv_auto('transaction_data.csv') t
  JOIN read_csv_auto('product.csv') p USING (PRODUCT_ID)
  WHERE t.WEEK_NO BETWEEN 17 AND 101
    AND p.DEPARTMENT NOT IN ('KIOSK-GAS','MISC SALES TRAN')
),
hh AS (
  SELECT household_key,
         SUM(SALES_VALUE)                     AS total_spend,
         COUNT(DISTINCT DAY)                  AS n_visit,
         (SELECT MAX(DAY) FROM tx) - MAX(DAY) AS recency
  FROM tx GROUP BY household_key
),
tiered AS (
  SELECT household_key, total_spend, n_visit, recency,
         NTILE(5) OVER (ORDER BY total_spend) AS tier
  FROM hh WHERE recency >= 35
)
SELECT
  CASE WHEN tier = 5 THEN '고가치' ELSE '기타' END AS value_seg,
  CASE WHEN recency < 70 THEN '이탈초기(35~69일)'
       ELSE '이미이탈(70일+)' END               AS timing_seg,
  COUNT(*)                AS households,
  ROUND(AVG(n_visit))     AS avg_visits,
  ROUND(AVG(total_spend)) AS avg_spend
FROM tiered
GROUP BY value_seg, timing_seg
ORDER BY value_seg, timing_seg;
