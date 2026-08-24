-- =============================================================
-- 01-1. 방문 간격 분포 (이탈 기준선)
-- 목적: "며칠 안 오면 이탈"인지 정하기 전, 정상 방문 리듬 파악
-- 방문 = (가구, 날짜) 단위 (같은 날 여러 결제는 1회로)
-- 결과: 중앙 4일 / p75 7일 / p90 14일 → 90%가 2주 안에 재방문하는 단골
-- =============================================================
WITH tx AS (
  SELECT t.household_key, t.DAY
  FROM read_csv_auto('transaction_data.csv') t
  JOIN read_csv_auto('product.csv') p USING (PRODUCT_ID)
  WHERE t.WEEK_NO BETWEEN 17 AND 101
    AND p.DEPARTMENT NOT IN ('KIOSK-GAS','MISC SALES TRAN')
),
visits AS (SELECT DISTINCT household_key, DAY FROM tx),
gaps AS (
  SELECT household_key,
         DAY - LAG(DAY) OVER (PARTITION BY household_key ORDER BY DAY) AS gap
  FROM visits
)
SELECT
  COUNT(*)                              AS n_gaps,
  ROUND(MEDIAN(gap),1)                  AS median_day,
  ROUND(QUANTILE_CONT(gap,0.25),1)      AS p25,
  ROUND(QUANTILE_CONT(gap,0.75),1)      AS p75,
  ROUND(QUANTILE_CONT(gap,0.90),1)      AS p90,
  ROUND(AVG(gap),1)                     AS avg_day
FROM gaps
WHERE gap IS NOT NULL;
