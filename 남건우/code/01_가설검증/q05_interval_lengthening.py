# 비즈니스 질문: "구매 주기가 길어지다가 사라지는" 가구가 실제로 있는가? 그 비율은?
#   (공지 가설 예시 1 — q04의 말기 비활동 정의를 이어받아 "사라지기 전 패턴"을 검증)
# 가정한 의사결정: 이탈 위험 조기 감지(간격 모니터링)를 리텐션 전략의 트리거로 쓸 수 있는지 판단
# 판정 기준: 말기 비활동 가구의 "마지막 3개 구매 간격 / 그 이전 자기 중앙 간격" 비율(ratio)이
#   활동 유지 가구보다 뚜렷이 높으면(배율 비교) "길어지다가 사라진다" 채택.
#   ratio 임계는 1.25 / 1.5 / 2.0 민감도 비교 후 확정.
# 주의: 간격 8개(방문 9회) 이상 가구만 패턴 판정 가능 — 커버리지를 반드시 보고.
#   말기 비활동은 관측 중단과 구분 불가(q04) — "이탈 확정"이 아니라 "위험 신호"로만 서술.
import duckdb
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "processed" / "dunnhumby.duckdb"
con = duckdb.connect(str(DB), read_only=True)

# 방문일 간 간격 + 뒤에서부터의 순번(rev_rank=1이 마지막 간격)
con.execute("""
CREATE OR REPLACE TEMP TABLE gaps AS
SELECT household_key, DAY,
       DAY - LAG(DAY) OVER (PARTITION BY household_key ORDER BY DAY) AS gap,
       ROW_NUMBER() OVER (PARTITION BY household_key ORDER BY DAY DESC) AS rev_rank
FROM (SELECT DISTINCT household_key, DAY FROM transactions_base)
QUALIFY gap IS NOT NULL
""")

# 가구별: 말기 비활동 여부(q04 개인화 임계) + 패턴 지표
# baseline = 마지막 3개를 제외한 간격의 중앙값, recent = 마지막 3개 간격 평균
con.execute("""
CREATE OR REPLACE TEMP TABLE hh_pattern AS
WITH hh_thr AS (
    SELECT household_key, COUNT(*) AS n_gaps,
           GREATEST(3 * MEDIAN(gap), 14) AS thr
    FROM gaps GROUP BY 1
),
base AS (
    SELECT household_key, MEDIAN(gap) AS baseline_med
    FROM gaps WHERE rev_rank > 3 GROUP BY 1
),
recent AS (
    SELECT household_key, AVG(gap) AS recent_avg, SUM(gap) AS recent_span
    FROM gaps WHERE rev_rank <= 3 GROUP BY 1
)
SELECT t.household_key, t.n_gaps, t.thr,
       r.recency, rfm.segment, rfm.m_score,
       (r.recency >= t.thr) AS is_inactive,
       b.baseline_med, c.recent_avg, c.recent_span,
       c.recent_avg / b.baseline_med AS ratio
FROM hh_thr t
JOIN hh_rfm rfm USING (household_key)
JOIN hh_rfm r USING (household_key)
LEFT JOIN base b USING (household_key)
LEFT JOIN recent c USING (household_key)
""")

print("### 커버리지 (패턴 판정 가능 가구)")
print(con.execute("""
SELECT COUNT(*) AS hh_with_gaps,
       COUNT(*) FILTER (n_gaps >= 8) AS hh_analyzable,
       ROUND(100.0 * COUNT(*) FILTER (n_gaps >= 8) / COUNT(*), 1) AS analyzable_pct,
       COUNT(*) FILTER (is_inactive) AS n_inactive,
       COUNT(*) FILTER (is_inactive AND n_gaps >= 8) AS n_inactive_analyzable
FROM hh_pattern
""").fetchdf().to_string(index=False))

print("\n### 말기 비활동 vs 활동 유지: 최근 간격 비율(ratio) 분포 (간격 8개 이상 가구)")
print(con.execute("""
SELECT is_inactive, COUNT(*) AS n_hh,
       ROUND(MEDIAN(ratio), 2) AS ratio_p50,
       ROUND(QUANTILE_CONT(ratio, 0.75), 2) AS ratio_p75,
       ROUND(100.0 * AVG(CASE WHEN ratio >= 1.25 THEN 1 ELSE 0 END), 1) AS pct_ge_125,
       ROUND(100.0 * AVG(CASE WHEN ratio >= 1.5 THEN 1 ELSE 0 END), 1) AS pct_ge_150,
       ROUND(100.0 * AVG(CASE WHEN ratio >= 2.0 THEN 1 ELSE 0 END), 1) AS pct_ge_200
FROM hh_pattern WHERE n_gaps >= 8
GROUP BY 1 ORDER BY 1 DESC
""").fetchdf().to_string(index=False))

print("\n### 4분면 (간격 8개 이상 가구, ratio 1.5 기준)")
print(con.execute("""
SELECT CASE WHEN is_inactive THEN '말기 비활동' ELSE '활동 유지' END AS status,
       CASE WHEN ratio >= 1.5 THEN '간격 확대(점진)' ELSE '간격 유지(급단절/안정)' END AS pattern,
       COUNT(*) AS n_hh,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_of_all
FROM hh_pattern WHERE n_gaps >= 8
GROUP BY 1, 2 ORDER BY 1 DESC, 2
""").fetchdf().to_string(index=False))

print("\n### 조기 감지 창: 말기 비활동+간격확대 가구의 마지막 3개 간격 합(일)")
print(con.execute("""
SELECT COUNT(*) AS n_hh,
       CAST(MEDIAN(recent_span) AS INT) AS span_p50,
       CAST(QUANTILE_CONT(recent_span, 0.25) AS INT) AS span_p25,
       CAST(QUANTILE_CONT(recent_span, 0.75) AS INT) AS span_p75
FROM hh_pattern WHERE n_gaps >= 8 AND is_inactive AND ratio >= 1.5
""").fetchdf().to_string(index=False))

print("\n### 유의성 검정: 간격확대 비율(≥1.5) 차이 — 두 비율 z검정 (정규 근사)")
import math
n1, x1, n2, x2 = con.execute("""
SELECT COUNT(*) FILTER (is_inactive),
       COUNT(*) FILTER (is_inactive AND ratio >= 1.5),
       COUNT(*) FILTER (NOT is_inactive),
       COUNT(*) FILTER (NOT is_inactive AND ratio >= 1.5)
FROM hh_pattern WHERE n_gaps >= 8
""").fetchone()
p1, p2, pp = x1 / n1, x2 / n2, (x1 + x2) / (n1 + n2)
z = (p1 - p2) / math.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n2))
p_two = math.erfc(abs(z) / math.sqrt(2))  # 양측 p값
print(f"비활동 {x1}/{n1} ({p1:.1%}) vs 활동 {x2}/{n2} ({p2:.1%})  "
      f"차이 {p1-p2:+.1%}  z={z:.2f}  p={p_two:.2e}")

print("\n### 세그먼트별: 말기 비활동 가구 중 간격 확대(점진) 비율 (간격 8개 이상)")
print(con.execute("""
SELECT segment, COUNT(*) AS n_inactive,
       COUNT(*) FILTER (ratio >= 1.5) AS n_lengthening,
       ROUND(100.0 * AVG(CASE WHEN ratio >= 1.5 THEN 1 ELSE 0 END), 1) AS lengthening_pct
FROM hh_pattern WHERE n_gaps >= 8 AND is_inactive
GROUP BY 1 ORDER BY 1
""").fetchdf().to_string(index=False))

con.close()
print("\nq05 done")
