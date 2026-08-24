# 비즈니스 질문: 캠페인 사전-사후 비교가 성립하는가 — (1) 그 가구가 받은 다른 캠페인과 겹치지 않는
#   "깨끗한" 전후 창을 가진 캠페인×가구 쌍이 얼마나 남고, (2) 그 부분집합에서 지출 규모가 비슷한
#   비교군(매칭)이 실제로 확보되는가?
# 가정한 의사결정: "예산 30% 삭감" 시나리오를 캠페인 단위 권고로 갈지, 타입 단위/다른 설계로
#   문안을 조정할지 (파일럿 게이트)
# 판정 기준: 깨끗한 쌍(60일 창)이 캠페인당 중앙값 50가구 이상이고 매칭 커버리지 70% 이상이면
#   캠페인 단위 유지. 미달이면 타입 단위 비교 또는 staggered(미래 수신 가구 비교군) 설계로 전환.
# 설계 주의(규칙 4): 산출되는 차이는 "매칭 사전-사후 차이(DID)"이며, 타겟팅이 관측 지출로만
#   매칭되므로 미관측 교란(전단 노출, 가구 사정)은 남는다. "효과" 아닌 "차이"로만 서술.
import duckdb
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "processed" / "dunnhumby.duckdb"
con = duckdb.connect(str(DB))
W = 60          # 전후 창 길이 (일)
CALIPER = 0.30  # pre 지출 매칭 허용 오차 (±30%)
FLOOR = 25.0    # pre 지출이 0에 가까운 가구의 절대 캘리퍼 ($)

con.execute("""
CREATE OR REPLACE TEMP VIEW hh_day AS
SELECT household_key, DAY, SUM(SALES_VALUE) AS spend
FROM transactions_base GROUP BY 1, 2
""")

# ── 수신 쌍 + 겹침 플래그 ──────────────────────────────────────────────
con.execute(f"""
CREATE OR REPLACE TEMP TABLE pairs AS
SELECT DISTINCT ct.household_key, ct.CAMPAIGN, cd.DESCRIPTION AS camp_type,
       cd.START_DAY AS s, cd.END_DAY AS e
FROM campaign_table ct JOIN campaign_desc cd USING (CAMPAIGN)
""")
n_pairs = con.execute("SELECT COUNT(*) FROM pairs").fetchone()[0]
print(f"수신 쌍(중복 제거): {n_pairs:,}")  # 조인 검증(규칙 6): campaign_table 7,208행 대비 확인

con.execute(f"""
CREATE OR REPLACE TEMP TABLE pair_flags AS
SELECT p.*,
       (p.s - {W} >= 1 AND p.s + {W} - 1 <= 711) AS window_ok,
       NOT EXISTS (SELECT 1 FROM pairs o
                   WHERE o.household_key = p.household_key AND o.CAMPAIGN != p.CAMPAIGN
                     AND o.s <= p.s + {W} - 1 AND o.e >= p.s - {W}) AS nooverlap60,
       NOT EXISTS (SELECT 1 FROM pairs o
                   WHERE o.household_key = p.household_key AND o.CAMPAIGN != p.CAMPAIGN
                     AND o.s <= p.s + 29 AND o.e >= p.s - 30) AS nooverlap30
FROM pairs p
""")

print("\n### [게이트 1] 깨끗한 캠페인×가구 쌍 — 전체 요약")
print(con.execute(f"""
SELECT COUNT(*) AS pairs_total,
       SUM(CASE WHEN window_ok THEN 1 ELSE 0 END) AS window_ok60,
       SUM(CASE WHEN window_ok AND nooverlap60 THEN 1 ELSE 0 END) AS clean60,
       SUM(CASE WHEN s - 30 >= 1 AND s + 29 <= 711 AND nooverlap30 THEN 1 ELSE 0 END) AS clean30,
       ROUND(100.0 * SUM(CASE WHEN window_ok AND nooverlap60 THEN 1 ELSE 0 END) / COUNT(*), 1) AS clean60_pct
FROM pair_flags
""").fetchdf().to_string(index=False))

print("\n### [게이트 1] 캠페인별 깨끗한 쌍 (타입별 요약 + 캠페인당 중앙값)")
print(con.execute("""
WITH per_camp AS (
    SELECT camp_type, CAMPAIGN,
           COUNT(*) AS recipients,
           SUM(CASE WHEN window_ok AND nooverlap60 THEN 1 ELSE 0 END) AS clean60,
           SUM(CASE WHEN s - 30 >= 1 AND s + 29 <= 711 AND nooverlap30 THEN 1 ELSE 0 END) AS clean30
    FROM pair_flags GROUP BY 1, 2)
SELECT camp_type, COUNT(*) AS n_campaigns,
       SUM(recipients) AS recipients, SUM(clean60) AS clean60_sum,
       CAST(MEDIAN(clean60) AS INT) AS clean60_med_per_camp,
       CAST(MEDIAN(clean30) AS INT) AS clean30_med_per_camp
FROM per_camp GROUP BY 1 ORDER BY 1
""").fetchdf().to_string(index=False))

# ── 창 지출 집계 (수신 쌍) ─────────────────────────────────────────────
con.execute(f"""
CREATE OR REPLACE TEMP TABLE r_spend AS
SELECT f.household_key, f.CAMPAIGN, f.camp_type, f.s,
       COALESCE(SUM(CASE WHEN d.DAY BETWEEN f.s - {W} AND f.s - 1 THEN d.spend END), 0) AS pre_spend,
       COALESCE(SUM(CASE WHEN d.DAY BETWEEN f.s AND f.s + {W} - 1 THEN d.spend END), 0) AS post_spend
FROM pair_flags f
LEFT JOIN hh_day d ON d.household_key = f.household_key
                  AND d.DAY BETWEEN f.s - {W} AND f.s + {W} - 1
WHERE f.window_ok AND f.nooverlap60
GROUP BY 1, 2, 3, 4
""")

# ── 비교군 풀 A: 캠페인 미수신 916가구 ────────────────────────────────
con.execute(f"""
CREATE OR REPLACE TEMP TABLE ctrl_never AS
SELECT c.CAMPAIGN, c.s, nr.household_key,
       COALESCE(SUM(CASE WHEN d.DAY BETWEEN c.s - {W} AND c.s - 1 THEN d.spend END), 0) AS pre_spend,
       COALESCE(SUM(CASE WHEN d.DAY BETWEEN c.s AND c.s + {W} - 1 THEN d.spend END), 0) AS post_spend
FROM (SELECT DISTINCT CAMPAIGN, s FROM pair_flags WHERE window_ok) c
CROSS JOIN (SELECT household_key FROM hh_rfm
            WHERE household_key NOT IN (SELECT DISTINCT household_key FROM campaign_table)) nr
LEFT JOIN hh_day d ON d.household_key = nr.household_key
                  AND d.DAY BETWEEN c.s - {W} AND c.s + {W} - 1
GROUP BY 1, 2, 3
""")

# ── 비교군 풀 B: 아직 안 받은 미래 수신 가구 (staggered, 첫 수신이 s+W 이후) ──
con.execute(f"""
CREATE OR REPLACE TEMP TABLE ctrl_notyet AS
SELECT c.CAMPAIGN, c.s, fr.household_key,
       COALESCE(SUM(CASE WHEN d.DAY BETWEEN c.s - {W} AND c.s - 1 THEN d.spend END), 0) AS pre_spend,
       COALESCE(SUM(CASE WHEN d.DAY BETWEEN c.s AND c.s + {W} - 1 THEN d.spend END), 0) AS post_spend
FROM (SELECT DISTINCT CAMPAIGN, s FROM pair_flags WHERE window_ok) c
JOIN (SELECT household_key, MIN(s) AS first_recv FROM pairs GROUP BY 1) fr
  ON fr.first_recv > c.s + {W} - 1
LEFT JOIN hh_day d ON d.household_key = fr.household_key
                  AND d.DAY BETWEEN c.s - {W} AND c.s + {W} - 1
GROUP BY 1, 2, 3
""")

def coverage(pool_sql, label):
    print(f"\n### [게이트 2] 매칭 커버리지 — {label}")
    print(con.execute(f"""
    WITH tier AS (SELECT household_key, COUNT(*) AS n_camp FROM pairs GROUP BY 1),
    matched AS (
        SELECT r.household_key, r.CAMPAIGN,
               CASE WHEN t.n_camp <= 2 THEN '1-2회' WHEN t.n_camp <= 5 THEN '3-5회' ELSE '6회+' END AS recv_tier,
               EXISTS (SELECT 1 FROM ({pool_sql}) k
                       WHERE k.CAMPAIGN = r.CAMPAIGN
                         AND ABS(k.pre_spend - r.pre_spend) <= GREATEST({CALIPER} * r.pre_spend, {FLOOR}))
               AS has_match
        FROM r_spend r JOIN tier t USING (household_key))
    SELECT recv_tier, COUNT(*) AS clean_pairs,
           ROUND(100.0 * AVG(CASE WHEN has_match THEN 1 ELSE 0 END), 1) AS matched_pct
    FROM matched GROUP BY 1
    UNION ALL
    SELECT '전체', COUNT(*), ROUND(100.0 * AVG(CASE WHEN has_match THEN 1 ELSE 0 END), 1)
    FROM matched ORDER BY 1
    """).fetchdf().to_string(index=False))

coverage("SELECT * FROM ctrl_never", "풀 A: 미수신 916가구")
coverage("SELECT * FROM ctrl_never UNION ALL SELECT * FROM ctrl_notyet", "풀 B: 미수신 ∪ 미래 수신(staggered)")

# ── 매칭 DID (풀 B, 깨끗한 쌍만): 주간 지출 변화량의 수신-비교군 차이 ──
print("\n### [참고] 매칭 사전-사후 차이 (풀 B, 주간 지출 기준, '차이'이지 '효과' 아님)")
print(con.execute(f"""
WITH pool AS (SELECT * FROM ctrl_never UNION ALL SELECT * FROM ctrl_notyet),
did AS (
    SELECT r.camp_type, r.household_key, r.CAMPAIGN,
           (r.post_spend - r.pre_spend) * 7.0 / {W} AS delta_r,
           (SELECT AVG((k.post_spend - k.pre_spend) * 7.0 / {W}) FROM pool k
            WHERE k.CAMPAIGN = r.CAMPAIGN
              AND ABS(k.pre_spend - r.pre_spend) <= GREATEST({CALIPER} * r.pre_spend, {FLOOR})) AS delta_c
    FROM r_spend r)
SELECT camp_type, COUNT(*) AS n_matched_pairs,
       ROUND(AVG(delta_r), 2) AS recipient_delta_wk,
       ROUND(AVG(delta_c), 2) AS control_delta_wk,
       ROUND(AVG(delta_r - delta_c), 2) AS did_wk,
       ROUND(MEDIAN(delta_r - delta_c), 2) AS did_wk_med,
       ROUND(100.0 * AVG(CASE WHEN delta_r > delta_c THEN 1 ELSE 0 END), 1) AS pct_above_ctrl
FROM did WHERE delta_c IS NOT NULL
GROUP BY 1 ORDER BY 1
""").fetchdf().to_string(index=False))

# ── 오염 심각도 참고치 ────────────────────────────────────────────────
print("\n### [참고] 겹침 심각도: 창(120일)당 같은 가구의 다른 활성 캠페인 수")
print(con.execute(f"""
SELECT ROUND(AVG(n_overlap), 2) AS avg_overlapping_campaigns,
       CAST(MEDIAN(n_overlap) AS INT) AS med, MAX(n_overlap) AS max
FROM (SELECT p.household_key, p.CAMPAIGN,
             (SELECT COUNT(*) FROM pairs o
              WHERE o.household_key = p.household_key AND o.CAMPAIGN != p.CAMPAIGN
                AND o.s <= p.s + {W} - 1 AND o.e >= p.s - {W}) AS n_overlap
      FROM pairs p WHERE p.window_ok) t
""".replace("p.window_ok", f"p.s - {W} >= 1 AND p.s + {W} - 1 <= 711")).fetchdf().to_string(index=False))

con.close()
print("\nq02 done")
