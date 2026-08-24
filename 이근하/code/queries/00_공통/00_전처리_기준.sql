-- =============================================================
-- 00. 공통 전처리 기준 (모든 분석의 출발점)
-- 엔진: DuckDB  |  실행 위치: 원본 CSV가 있는 폴더
-- -------------------------------------------------------------
-- 팀 전체가 같은 숫자를 보도록 모든 쿼리에 아래 전처리를 공통 적용한다.
--   · 분석 구간 W17~W101  : W1~16은 매출 증가가 아니라 '패널 편입' 구간
--   · 비장보기 부문 제외   : KIOSK-GAS(주유), MISC SALES TRAN(기타결제) = 매출 ~8%
--   · 매출 컬럼 = SALES_VALUE (할인 반영 후 매장 매출)
--
-- 검증값: 거래 2,346,445행 / 가구 2,492 / 바스켓 229,582 / 매출 6,755,160
--        (DuckDB ↔ pandas 동일 값 교차검증 완료)
-- =============================================================

-- 공통 CTE (다른 쿼리들은 이 tx 블록을 앞에 붙여 사용)
WITH tx AS (
  SELECT t.*, p.DEPARTMENT, p.COMMODITY_DESC
  FROM read_csv_auto('transaction_data.csv') t
  JOIN read_csv_auto('product.csv') p USING (PRODUCT_ID)
  WHERE t.WEEK_NO BETWEEN 17 AND 101
    AND p.DEPARTMENT NOT IN ('KIOSK-GAS','MISC SALES TRAN')
)
SELECT
  COUNT(*)                        AS rows,
  COUNT(DISTINCT household_key)   AS households,
  COUNT(DISTINCT BASKET_ID)       AS baskets,
  ROUND(SUM(SALES_VALUE))         AS sales
FROM tx;
