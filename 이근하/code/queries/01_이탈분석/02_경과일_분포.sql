-- =============================================================
-- 01-2. 마지막 방문 후 경과일 분포 (7일 버킷, 누적)
-- 목적: 경과일이 어디서 꺾이는지 데이터로 확인 (경계를 미리 정하지 않음)
-- 결과: 85%가 5주(35일) 안에 재방문. 그 뒤부터 꼬리(진짜 떠나는 집단)
-- =============================================================
WITH tx AS (
  SELECT t.household_key, t.DAY, t.WEEK_NO
  FROM read_csv_auto('transaction_data.csv') t
  JOIN read_csv_auto('product.csv') p USING (PRODUCT_ID)
  WHERE t.WEEK_NO BETWEEN 17 AND 101
    AND p.DEPARTMENT NOT IN ('KIOSK-GAS','MISC SALES TRAN')
),
recency AS (
  SELECT household_key,
         (SELECT MAX(DAY) FROM tx) - MAX(DAY) AS days_since
  FROM tx GROUP BY household_key
)
SELECT
  (days_since // 7)                    AS week_bucket,
  (days_since // 7) * 7                AS from_day,
  COUNT(*)                             AS households,
  ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER (),1) AS pct,
  ROUND(100.0*SUM(COUNT(*)) OVER (ORDER BY days_since//7)
        /SUM(COUNT(*)) OVER (),1)      AS cumulative_pct
FROM recency
GROUP BY days_since // 7
ORDER BY week_bucket;
