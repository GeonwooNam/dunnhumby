-- =============================================================
-- 03-3. 쿠폰은 언제 쓰이나 — 최근 선호 매칭
-- 목적: 캠페인 직전 56일에 산 카테고리와 쿠폰 카테고리가 맞는지별 사용률
--   (2년 전체로 보면 98%가 '맞음'으로 뭉개짐 → 시점을 직전으로 좁혀야 신호가 보임)
-- 결과: 최근 관심 없음 0% / 1~2개 겹침 4.8% / 3개+ 13.4%
--       → 쿠폰은 '지금 그 사람이 원하는 것'에 맞을 때만 작동
-- =============================================================
WITH tx AS (
  SELECT t.household_key, t.DAY, p.COMMODITY_DESC
  FROM read_csv_auto('transaction_data.csv') t
  JOIN read_csv_auto('product.csv') p USING (PRODUCT_ID)
  WHERE t.WEEK_NO BETWEEN 17 AND 101
    AND p.DEPARTMENT NOT IN ('KIOSK-GAS','MISC SALES TRAN')
),
camp_cat AS (   -- 캠페인별 쿠폰 대상 카테고리
  SELECT DISTINCT c.CAMPAIGN, p.COMMODITY_DESC
  FROM read_csv_auto('coupon.csv') c
  JOIN read_csv_auto('product.csv') p USING (PRODUCT_ID)
),
pairs AS (      -- (가구,캠페인) + 캠페인 시작일
  SELECT DISTINCT ct.household_key, ct.CAMPAIGN, cd.START_DAY
  FROM read_csv_auto('campaign_table.csv') ct
  JOIN read_csv_auto('campaign_desc.csv') cd USING (CAMPAIGN)
),
match AS (      -- 캠페인 직전 56일 구매 카테고리와 쿠폰 카테고리 겹침 수
  SELECT pr.household_key, pr.CAMPAIGN,
         COUNT(DISTINCT cc.COMMODITY_DESC) FILTER (recent.COMMODITY_DESC IS NOT NULL) AS 겹치는수
  FROM pairs pr
  JOIN camp_cat cc ON cc.CAMPAIGN = pr.CAMPAIGN
  LEFT JOIN (
    SELECT DISTINCT t.household_key, t.COMMODITY_DESC, pr2.CAMPAIGN
    FROM tx t
    JOIN pairs pr2 ON pr2.household_key = t.household_key
                  AND t.DAY BETWEEN pr2.START_DAY - 56 AND pr2.START_DAY - 1
  ) recent ON recent.household_key = pr.household_key
          AND recent.CAMPAIGN = pr.CAMPAIGN
          AND recent.COMMODITY_DESC = cc.COMMODITY_DESC
  GROUP BY pr.household_key, pr.CAMPAIGN
),
used AS (SELECT DISTINCT household_key, CAMPAIGN FROM read_csv_auto('coupon_redempt.csv'))
SELECT
  CASE WHEN 겹치는수 = 0 THEN '1) 최근 관심 없음'
       WHEN 겹치는수 <= 2 THEN '2) 1~2개 겹침'
       ELSE '3) 3개+ 겹침' END AS 최근선호일치,
  COUNT(*)                     AS 쌍수,
  ROUND(100.0*COUNT(*) FILTER ((household_key,CAMPAIGN) IN (SELECT (household_key,CAMPAIGN) FROM used))
        / COUNT(*),1)          AS 사용률
FROM match
GROUP BY 최근선호일치
ORDER BY 최근선호일치;
