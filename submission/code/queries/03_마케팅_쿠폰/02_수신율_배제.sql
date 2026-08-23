-- =============================================================
-- 03-2. 위험군 우량고객이 쿠폰에서 배제되는가
-- 목적: 씀씀이(방문당 지출)가 비슷한 우량고객끼리 수신/사용률 비교
--   위험군 top20% vs 정상군 top20% (각 집단 내 방문당 지출 상위 20%)
-- 결과: 방문당 지출 45 vs 51(거의 같음)인데 수신율 41.8% vs 81.8%
--       → 방어가 필요한 순간 쿠폰이 안 닿음
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
         SUM(SALES_VALUE) / COUNT(DISTINCT DAY) AS spend_per_visit,
         COUNT(DISTINCT DAY)                    AS n_visit,
         (SELECT MAX(DAY) FROM tx) - MAX(DAY)   AS recency
  FROM tx GROUP BY household_key
),
tiered AS (
  SELECT household_key, spend_per_visit,
         CASE WHEN recency >= 35 THEN '위험군' ELSE '정상군' END AS status,
         NTILE(5) OVER (PARTITION BY (recency >= 35) ORDER BY spend_per_visit) AS tier
  FROM hh WHERE n_visit >= 4
),
received AS (SELECT DISTINCT household_key FROM read_csv_auto('campaign_table.csv')),
used     AS (SELECT DISTINCT household_key FROM read_csv_auto('coupon_redempt.csv'))
SELECT
  status,
  COUNT(*)                                                        AS households,
  ROUND(MEDIAN(spend_per_visit),1)                                AS 방문당지출,
  ROUND(100.0*COUNT(*) FILTER (household_key IN (SELECT household_key FROM received))/COUNT(*),1) AS 받음_pct,
  ROUND(100.0*COUNT(*) FILTER (household_key IN (SELECT household_key FROM used))/COUNT(*),1)     AS 씀_pct,
  ROUND(100.0*COUNT(*) FILTER (household_key IN (SELECT household_key FROM used))
        / NULLIF(COUNT(*) FILTER (household_key IN (SELECT household_key FROM received)),0),1)    AS 받은사람중_사용률
FROM tiered
WHERE tier = 5
GROUP BY status
ORDER BY status;
