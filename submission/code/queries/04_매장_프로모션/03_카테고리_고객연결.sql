-- =============================================================
-- 04-3. 검증 카테고리 × 고객 연결 (두 레버 결합 가능성 검증)
-- 목적: 결합 프로모션 검증 카테고리(BACON 등)를 고가치 고객이 사는가
--   → 개인 맞춤 프로모션으로 쿠폰·진열을 합칠 수 있는지 확인
-- 결과: '산다'로 보면 대부분 70%+ 겹치지만, '주력으로 사면서+뜸해지는 중'으로
--       좁히면 각 카테고리 0~1가구로 무너짐 → 두 레버는 개인 단위로 못 합침
--       (진열은 개인 겨냥 불가 → 쿠폰=개인 / 진열=매장 으로 분리)
-- 아래는 '고가치 고객의 검증 7개 카테고리 선호율' (겹침 확인 단계)
-- =============================================================
WITH tx AS (
  SELECT t.household_key, t.BASKET_ID, t.DAY, t.SALES_VALUE, p.COMMODITY_DESC
  FROM read_csv_auto('transaction_data.csv') t
  JOIN read_csv_auto('product.csv') p USING (PRODUCT_ID)
  WHERE t.WEEK_NO BETWEEN 17 AND 101
    AND p.DEPARTMENT NOT IN ('KIOSK-GAS','MISC SALES TRAN')
),
hh AS (
  SELECT household_key, SUM(SALES_VALUE) AS spend,
         (SELECT MAX(DAY) FROM tx) - MAX(DAY) AS recency
  FROM tx GROUP BY household_key
),
hv AS (   -- 고가치 = 지출 상위 20%
  SELECT household_key FROM (
    SELECT household_key, NTILE(5) OVER (ORDER BY spend) AS tier FROM hh
  ) WHERE tier = 5
),
pref AS (  -- 선호 = 서로 다른 장바구니 2회 이상 구매
  SELECT DISTINCT household_key, COMMODITY_DESC FROM (
    SELECT household_key, COMMODITY_DESC, COUNT(DISTINCT BASKET_ID) AS n
    FROM tx GROUP BY household_key, COMMODITY_DESC
  ) WHERE n >= 2
),
target(cat) AS (VALUES
  ('BACON'),('LUNCHMEAT'),('DINNER SAUSAGE'),
  ('BREAKFAST SAUSAGE/SANDWICHES'),('SOFT DRINKS'),('PIES'),('WAREHOUSE SNACKS'))
SELECT
  t.cat AS 카테고리,
  COUNT(DISTINCT hv.household_key) FILTER (p.household_key IS NOT NULL) AS 선호_고가치가구,
  ROUND(100.0*COUNT(DISTINCT hv.household_key) FILTER (p.household_key IS NOT NULL)
        / COUNT(DISTINCT hv.household_key), 1) AS 고가치중_비율
FROM target t
CROSS JOIN hv
LEFT JOIN pref p ON p.household_key = hv.household_key AND p.COMMODITY_DESC = t.cat
GROUP BY t.cat
ORDER BY 선호_고가치가구 DESC;
