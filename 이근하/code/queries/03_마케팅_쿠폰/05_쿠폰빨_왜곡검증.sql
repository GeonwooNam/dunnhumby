-- =============================================================
-- 03-5. (보조) 쿠폰빨 왜곡 검증
-- 목적: "쿠폰으로 버티는 고객"이 정상군에 섞여 이탈률을 왜곡하나?
-- 방법: 정상군을 지출 5층으로 나눠, 각 층에서 쿠폰 사용 유무별 이탈률 비교
-- 결과: 모든 층에서 차이 없음(0~2%대) → 쿠폰빨 왜곡 없음, 이탈 분석 안전
--       (부수 발견: 쿠폰 사용 가구가 최저층 1명 → 최고층 162명, 고지출 쏠림)
-- =============================================================
WITH tx AS (
  SELECT t.household_key, t.DAY, t.WEEK_NO, t.SALES_VALUE
  FROM read_csv_auto('transaction_data.csv') t
  JOIN read_csv_auto('product.csv') p USING (PRODUCT_ID)
  WHERE t.WEEK_NO BETWEEN 17 AND 101
    AND p.DEPARTMENT NOT IN ('KIOSK-GAS','MISC SALES TRAN')
),
obs_end AS (SELECT MAX(DAY) AS d FROM tx WHERE WEEK_NO <= 80),
obs AS (
  SELECT household_key, SUM(SALES_VALUE) AS spend,
         COUNT(DISTINCT DAY) AS n_visit, MAX(DAY) AS last_day
  FROM tx WHERE WEEK_NO <= 80 GROUP BY household_key
),
future AS (SELECT DISTINCT household_key FROM tx WHERE WEEK_NO > 80),
coupon_users AS (
  SELECT DISTINCT household_key FROM read_csv_auto('coupon_redempt.csv')
  WHERE DAY <= (SELECT d FROM obs_end)
),
panel AS (
  SELECT o.household_key,
         (o.household_key IN (SELECT household_key FROM coupon_users)) AS used_coupon,
         (f.household_key IS NULL) AS churned,
         NTILE(5) OVER (ORDER BY o.spend) AS spend_tier
  FROM obs o LEFT JOIN future f USING (household_key)
  WHERE o.n_visit >= 4
    AND ((SELECT d FROM obs_end) - o.last_day) < 35     -- 정상군만
)
SELECT
  spend_tier,
  COUNT(*) FILTER (used_coupon)                          AS coupon_hh,
  ROUND(100.0*AVG(churned::INT) FILTER (used_coupon),1)  AS churn_coupon,
  COUNT(*) FILTER (NOT used_coupon)                      AS nocoupon_hh,
  ROUND(100.0*AVG(churned::INT) FILTER (NOT used_coupon),1) AS churn_nocoupon
FROM panel
GROUP BY spend_tier ORDER BY spend_tier;
