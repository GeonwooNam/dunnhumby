-- =============================================================
-- 03-1. 셀렉션 바이어스 — 타겟은 개입 전부터 우량고객인가
-- 목적: "쿠폰 받은 사람 매출↑"이 쿠폰 덕인지 원래 우량인지 구분
-- 방법: 캠페인 '시작 직전 56일' 지출만 비교 (사후 오염 없음)
-- 결과: 타겟이 비타겟보다 중앙 3.52배 (전수 30/30 캠페인 편향). 대표 4개 예시.
--       → 단순 사후 비교는 효과 과대추정 → DiD/매칭 필수
-- =============================================================
WITH tx AS (
  SELECT t.household_key, t.DAY, t.SALES_VALUE
  FROM read_csv_auto('transaction_data.csv') t
  JOIN read_csv_auto('product.csv') p USING (PRODUCT_ID)
  WHERE t.WEEK_NO BETWEEN 17 AND 101
    AND p.DEPARTMENT NOT IN ('KIOSK-GAS','MISC SALES TRAN')
),
camp AS (
  SELECT CAMPAIGN, START_DAY
  FROM read_csv_auto('campaign_desc.csv')
  WHERE CAMPAIGN IN (8, 13, 18, 26)          -- 타겟 규모 큰 대표 캠페인
),
tgt AS (SELECT DISTINCT CAMPAIGN, household_key FROM read_csv_auto('campaign_table.csv')),
pre AS (
  SELECT c.CAMPAIGN, h.household_key,
         (t2.household_key IS NOT NULL) AS is_target,
         COALESCE(SUM(tx.SALES_VALUE), 0) AS pre_spend
  FROM camp c
  CROSS JOIN (SELECT DISTINCT household_key FROM tx) h
  LEFT JOIN tgt t2 ON t2.CAMPAIGN = c.CAMPAIGN AND t2.household_key = h.household_key
  LEFT JOIN tx ON tx.household_key = h.household_key
             AND tx.DAY BETWEEN c.START_DAY - 56 AND c.START_DAY - 1
  GROUP BY c.CAMPAIGN, h.household_key, is_target
)
SELECT CAMPAIGN,
       CASE WHEN is_target THEN '타겟' ELSE '비타겟' END AS grp,
       COUNT(*)                     AS households,
       ROUND(MEDIAN(pre_spend),1)   AS median_pre_spend
FROM pre
GROUP BY CAMPAIGN, is_target
ORDER BY CAMPAIGN, is_target DESC;
