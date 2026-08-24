-- =============================================================
-- 01-3. 이탈 정의 홀드아웃 검증 (경과일 구간별 실제 이탈률)
-- 목적: 답을 보고 기준 만드는 오류 방지 — 관측/미래를 나눠 채점
--   관측 W17~80 시점에 경과일로 판정 → 미래 W81~101 재방문으로 정답 채점
--   대상: 관측구간 방문 4회 이상 (패턴이 있는 가구)
-- 결과: 34일까지 1.1% 평탄 → 35일에서 5.7%로 5배 급증 → 위험군 = 35일+
--       (전체 2,408가구 중 실제 이탈 73가구 = 기저 3.0%)
-- =============================================================
WITH tx AS (
  SELECT t.household_key, t.DAY, t.WEEK_NO
  FROM read_csv_auto('transaction_data.csv') t
  JOIN read_csv_auto('product.csv') p USING (PRODUCT_ID)
  WHERE t.WEEK_NO BETWEEN 17 AND 101
    AND p.DEPARTMENT NOT IN ('KIOSK-GAS','MISC SALES TRAN')
),
obs_end AS (SELECT MAX(DAY) AS d FROM tx WHERE WEEK_NO <= 80),
obs AS (
  SELECT household_key, COUNT(DISTINCT DAY) AS n_visit, MAX(DAY) AS last_day
  FROM tx WHERE WEEK_NO <= 80 GROUP BY household_key
),
future AS (SELECT DISTINCT household_key FROM tx WHERE WEEK_NO > 80),
panel AS (
  SELECT (SELECT d FROM obs_end) - o.last_day AS recency,
         (f.household_key IS NULL) AS churned          -- 미래에 안 왔으면 이탈
  FROM obs o LEFT JOIN future f USING (household_key)
  WHERE o.n_visit >= 4
)
SELECT
  CASE
    WHEN recency < 21 THEN '1) ~20일'
    WHEN recency < 28 THEN '2) 21~27'
    WHEN recency < 35 THEN '3) 28~34'
    WHEN recency < 42 THEN '4) 35~41'
    WHEN recency < 49 THEN '5) 42~48'
    ELSE                   '6) 49일+'
  END                              AS recency_group,
  COUNT(*)                         AS households,
  SUM(churned::INT)                AS churned,
  ROUND(100.0*AVG(churned::INT),1) AS churn_pct,
  -- 이 구간 이상을 위험군으로 볼 때의 이탈자 포착률(recall)
  ROUND(100.0*SUM(SUM(churned::INT)) OVER (ORDER BY MIN(recency) DESC)
        / (SELECT SUM(churned::INT) FROM panel), 1) AS captures_pct
FROM panel
GROUP BY recency_group
ORDER BY recency_group;
