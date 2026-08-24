# [가설 1] 사라지는 가구는 사전 징후가 있다
# 질문 1: "이탈"(말기 비활동)을 어디에 그어야 안정적인가 — 글로벌 고정 임계 vs 개인화 임계
# 질문 2: 말기 비활동 가구는 사라지기 전에 구매 간격이 벌어지는 패턴을 보이는가? 그 비율은?
# 판정: (1) 글로벌 임계가 라이트 쇼퍼를 과잉 판정하면 개인화 임계(자기 중앙 간격×3, 하한 14일) 채택
#       (2) 비활동 가구의 "마지막 3개 간격/평소 중앙 간격" 비율이 활동 가구보다 뚜렷이 높으면
#           "길어지다가 사라진다" 채택 (z검정 병행)
# 주의: 관측이 711일에 끊기므로 "이탈"이 아니라 "말기 비활동" — 관측 중단과 구분 불가.
#   패턴 판정은 간격 8개(방문 9회) 이상 가구만 가능 — 커버리지를 함께 보고.
# 선행: 01_segments.py (hh_rfm 필요)
import math
import duckdb
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "processed" / "dunnhumby.duckdb"
con = duckdb.connect(str(DB), read_only=True)

# 방문일(가구×DAY) 간 간격. rev_rank=1이 마지막 간격
con.execute("""
CREATE OR REPLACE TEMP TABLE gaps AS
SELECT household_key,
       DAY - LAG(DAY) OVER (PARTITION BY household_key ORDER BY DAY) AS gap,
       ROW_NUMBER() OVER (PARTITION BY household_key ORDER BY DAY DESC) AS rev_rank
FROM (SELECT DISTINCT household_key, DAY FROM transactions_base)
QUALIFY gap IS NOT NULL
""")

# ── 1. 임계 정의: 글로벌 고정 vs 개인화 ──
print("### 가구별 중앙 구매 간격 (F 사분위별) — 헤비/라이트 쇼퍼 이질성")
print(con.execute("""
WITH hh_gap AS (SELECT household_key, MEDIAN(gap) AS med_gap FROM gaps GROUP BY 1)
SELECT r.f_score, COUNT(*) AS n_hh,
       CAST(MEDIAN(g.med_gap) AS INT) AS med_of_med_gap
FROM hh_rfm r JOIN hh_gap g USING (household_key)
GROUP BY 1 ORDER BY 1
""").fetchdf().to_string(index=False))

print("\n### 말기 비활동률: 글로벌 28일 vs 개인화(자기 중앙 간격×3, 하한 14일)")
print(con.execute("""
WITH hh_gap AS (SELECT household_key, GREATEST(3 * MEDIAN(gap), 14) AS thr FROM gaps GROUP BY 1)
SELECT r.f_score, COUNT(*) AS n_hh,
       ROUND(100.0 * AVG(CASE WHEN r.recency >= 28 THEN 1 ELSE 0 END), 1) AS global28_pct,
       ROUND(100.0 * AVG(CASE WHEN r.recency >= g.thr THEN 1 ELSE 0 END), 1) AS personal_pct
FROM hh_rfm r JOIN hh_gap g USING (household_key)
GROUP BY 1
UNION ALL
SELECT NULL, COUNT(*),
       ROUND(100.0 * AVG(CASE WHEN r.recency >= 28 THEN 1 ELSE 0 END), 1),
       ROUND(100.0 * AVG(CASE WHEN r.recency >= g.thr THEN 1 ELSE 0 END), 1)
FROM hh_rfm r JOIN hh_gap g USING (household_key)
ORDER BY 1 NULLS LAST
""").fetchdf().to_string(index=False))
print("→ 글로벌 28일은 F1(라이트)의 절반을 이탈 판정 (F4의 14배). 개인화는 3.8배로 압축 → 개인화 채택")

# ── 2. 사전 징후: 마지막 3개 간격 vs 그 이전 자기 중앙 간격 ──
con.execute("""
CREATE OR REPLACE TEMP TABLE hh_pattern AS
WITH hh_thr AS (
    SELECT household_key, COUNT(*) AS n_gaps, GREATEST(3 * MEDIAN(gap), 14) AS thr
    FROM gaps GROUP BY 1),
base AS (SELECT household_key, MEDIAN(gap) AS baseline_med FROM gaps WHERE rev_rank > 3 GROUP BY 1),
recent AS (SELECT household_key, AVG(gap) AS recent_avg, SUM(gap) AS recent_span
           FROM gaps WHERE rev_rank <= 3 GROUP BY 1)
SELECT t.household_key, t.n_gaps, rfm.segment,
       (rfm.recency >= t.thr) AS is_inactive,
       c.recent_avg / b.baseline_med AS ratio,
       c.recent_span
FROM hh_thr t
JOIN hh_rfm rfm USING (household_key)
LEFT JOIN base b USING (household_key)
LEFT JOIN recent c USING (household_key)
""")

print("\n### 말기 비활동 vs 활동 유지: 최근 간격 비율(ratio) — 간격 8개 이상 가구")
print(con.execute("""
SELECT is_inactive, COUNT(*) AS n_hh,
       ROUND(MEDIAN(ratio), 2) AS ratio_p50,
       ROUND(100.0 * AVG(CASE WHEN ratio >= 1.5 THEN 1 ELSE 0 END), 1) AS pct_ge_150,
       ROUND(100.0 * AVG(CASE WHEN ratio >= 2.0 THEN 1 ELSE 0 END), 1) AS pct_ge_200
FROM hh_pattern WHERE n_gaps >= 8
GROUP BY 1 ORDER BY 1 DESC
""").fetchdf().to_string(index=False))

n1, x1, n2, x2 = con.execute("""
SELECT COUNT(*) FILTER (is_inactive), COUNT(*) FILTER (is_inactive AND ratio >= 1.5),
       COUNT(*) FILTER (NOT is_inactive), COUNT(*) FILTER (NOT is_inactive AND ratio >= 1.5)
FROM hh_pattern WHERE n_gaps >= 8
""").fetchone()
p1, p2, pp = x1 / n1, x2 / n2, (x1 + x2) / (n1 + n2)
z = (p1 - p2) / math.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n2))
print(f"두 비율 z검정: 비활동 {p1:.1%} vs 활동 {p2:.1%}, 차이 {p1-p2:+.1%}p, "
      f"z={z:.2f}, p={math.erfc(abs(z) / math.sqrt(2)):.2e}")

print("\n### 4분면 (전체 판정 가능 가구 대비 비율, ratio 1.5 기준)")
print(con.execute("""
SELECT CASE WHEN is_inactive THEN '말기 비활동' ELSE '활동 유지' END AS status,
       CASE WHEN ratio >= 1.5 THEN '간격 확대(점진)' ELSE '간격 유지(급단절/안정)' END AS pattern,
       COUNT(*) AS n_hh,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_of_all
FROM hh_pattern WHERE n_gaps >= 8
GROUP BY 1, 2 ORDER BY 1 DESC, 2
""").fetchdf().to_string(index=False))

print("\n### 조기 감지 창 + 타겟 리스트 크기")
print(con.execute("""
SELECT CAST(MEDIAN(recent_span) AS INT) AS 감지창_p50_일,
       COUNT(*) AS 점진형_비활동_가구,
       COUNT(*) FILTER (segment = 'S2_고액휴면') AS 그중_S2_고액휴면
FROM hh_pattern WHERE n_gaps >= 8 AND is_inactive AND ratio >= 1.5
""").fetchdf().to_string(index=False))

con.close()
print("\n02_churn_signal done")
