# 비즈니스 질문: 구매 간격 분포 기준으로 "이탈"을 어디에 그으면 안정적인가?
# 가정한 의사결정: 권고안에서 "이탈 위험 세그먼트" 정의로 채택할 임계값 확정
#   (글로벌 고정 임계 vs 가구별 개인화 임계)
# 판정 기준: 임계값 28/42/56일별 말기 이탈률과, F(방문빈도) 사분위별 이탈률 왜곡을 비교.
#   글로벌 임계가 라이트 쇼퍼를 과잉 판정하면 개인화 임계(자기 중앙 간격의 3배) 채택.
# 주의: 좌측 절단 — 관측 종료(711일) 시점 비활동을 "이탈"로 부르는 것은 관측 중단과 구분 불가.
#   "말기 비활동"으로만 서술하고, 진짜 이탈 검증은 추가 기간 데이터 필요(한계 명시).
import duckdb
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "processed" / "dunnhumby.duckdb"
con = duckdb.connect(str(DB))

con.execute("""
CREATE OR REPLACE TEMP TABLE gaps AS
SELECT household_key, DAY - LAG(DAY) OVER (PARTITION BY household_key ORDER BY DAY) AS gap
FROM (SELECT DISTINCT household_key, DAY FROM transactions_base)
QUALIFY gap IS NOT NULL
""")

print("### 구매 간격(방문일 간) 글로벌 분포")
print(con.execute("""
SELECT COUNT(*) AS n_gaps,
       CAST(MEDIAN(gap) AS INT) AS p50,
       CAST(QUANTILE_CONT(gap, 0.75) AS INT) AS p75,
       CAST(QUANTILE_CONT(gap, 0.90) AS INT) AS p90,
       CAST(QUANTILE_CONT(gap, 0.95) AS INT) AS p95
FROM gaps
""").fetchdf().to_string(index=False))

print("\n### F 사분위별 개인 중앙 간격 (헤비/라이트 쇼퍼 이질성)")
print(con.execute("""
WITH hh_gap AS (SELECT household_key, MEDIAN(gap) AS med_gap FROM gaps GROUP BY 1)
SELECT r.f_score,
       COUNT(*) AS n_hh,
       CAST(MEDIAN(g.med_gap) AS INT) AS med_of_med_gap,
       CAST(QUANTILE_CONT(g.med_gap, 0.90) AS INT) AS p90_of_med_gap
FROM hh_rfm r JOIN hh_gap g USING (household_key)
GROUP BY 1 ORDER BY 1
""").fetchdf().to_string(index=False))

print("\n### 글로벌 임계값별 말기 비활동률 (711일 기준, F 사분위별)")
print(con.execute("""
SELECT r.f_score, COUNT(*) AS n_hh,
       ROUND(100.0 * AVG(CASE WHEN r.recency >= 28 THEN 1 ELSE 0 END), 1) AS inact28_pct,
       ROUND(100.0 * AVG(CASE WHEN r.recency >= 42 THEN 1 ELSE 0 END), 1) AS inact42_pct,
       ROUND(100.0 * AVG(CASE WHEN r.recency >= 56 THEN 1 ELSE 0 END), 1) AS inact56_pct
FROM hh_rfm r GROUP BY 1
UNION ALL
SELECT NULL, COUNT(*),
       ROUND(100.0 * AVG(CASE WHEN recency >= 28 THEN 1 ELSE 0 END), 1),
       ROUND(100.0 * AVG(CASE WHEN recency >= 42 THEN 1 ELSE 0 END), 1),
       ROUND(100.0 * AVG(CASE WHEN recency >= 56 THEN 1 ELSE 0 END), 1)
FROM hh_rfm ORDER BY 1 NULLS LAST
""").fetchdf().to_string(index=False))

print("\n### 개인화 임계(자기 중앙 간격 × 3, 하한 14일)별 말기 비활동률")
print(con.execute("""
WITH hh_gap AS (SELECT household_key, GREATEST(3 * MEDIAN(gap), 14) AS thr FROM gaps GROUP BY 1)
SELECT r.f_score, COUNT(*) AS n_hh,
       ROUND(100.0 * AVG(CASE WHEN r.recency >= g.thr THEN 1 ELSE 0 END), 1) AS inact_personal_pct
FROM hh_rfm r JOIN hh_gap g USING (household_key)
GROUP BY 1
UNION ALL
SELECT NULL, COUNT(*), ROUND(100.0 * AVG(CASE WHEN r.recency >= g.thr THEN 1 ELSE 0 END), 1)
FROM hh_rfm r JOIN hh_gap g USING (household_key)
ORDER BY 1 NULLS LAST
""").fetchdf().to_string(index=False))

con.close()
print("\nq04 done")
