# [가설 2] 캠페인 효과처럼 보이는 것의 대부분은 착시다
# 4단계로 좁혀 들어간다:
#   1) 순진한 비교 — 수신 가구가 4.3배 더 쓴다 (그러나 이건 효과가 아니다)
#   2) 셀프셀렉션 확인 — 쿠폰 상환도 원래 고액 가구에 몰려 있다 (q03)
#   3) 매칭 사전-사후 — 깨끗한 창 + 지출 매칭으로 편향을 걷어내면 증분은 주당 $3 수준 (q02)
#   4) 세그먼트 분해 — 그 $3도 평균의 착시. 고액은 +, 저액은 − (심슨의 역설, q06)
# 판정: n≥30 셀에서 DID 부호가 뒤집히면 "타입 단위 평균" 인용 금지 → 타입×세그먼트로 서술
# 주의: 산출되는 차이는 "매칭 사전-사후 차이"이지 "효과"가 아니다(미관측 교란 잔존).
#   세그먼트가 전 기간 기준이라 결과 창과 겹침(내생성) — 본분석에서 사전 창 기준 재산정 필요.
# 선행: 01_segments.py (hh_rfm 필요)
import duckdb
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "processed" / "dunnhumby.duckdb"
con = duckdb.connect(str(DB), read_only=True)
W = 60          # 전후 창 길이 (일)
CALIPER = 0.30  # pre 지출 매칭 허용 오차 (±30%)
FLOOR = 25.0    # pre 지출이 0에 가까운 가구의 절대 캘리퍼 ($)

# ── 1. 순진한 비교 (이 표가 왜 금지인지가 아래 단계들의 내용) ──
print("### [1단계] 캠페인 수신 여부별 2년 총지출 — '차이'는 크다")
print(con.execute("""
WITH spend AS (SELECT household_key, SUM(SALES_VALUE) AS net_spend
               FROM transactions_base GROUP BY 1),
     recv AS (SELECT DISTINCT household_key FROM campaign_table)
SELECT CASE WHEN r.household_key IS NOT NULL THEN '수신(1회 이상)' ELSE '미수신' END AS grp,
       COUNT(*) AS n_hh, ROUND(AVG(net_spend)) AS mean_spend, ROUND(MEDIAN(net_spend)) AS med_spend
FROM spend s LEFT JOIN recv r USING (household_key)
GROUP BY 1 ORDER BY 1
""").fetchdf().to_string(index=False))

# ── 2. 셀프셀렉션: 상환 가구는 애초에 고액 가구 ──
print("\n### [2단계] 수신 가구 내 상환 vs 비상환 가구의 지출 (상환 = M의 재표현)")
print(con.execute("""
WITH recip AS (SELECT DISTINCT household_key FROM campaign_table),
     red   AS (SELECT DISTINCT household_key FROM coupon_redempt)
SELECT CASE WHEN d.household_key IS NOT NULL THEN '상환' ELSE '비상환' END AS grp,
       COUNT(*) AS n_hh, ROUND(MEDIAN(r.monetary)) AS med_spend, ROUND(AVG(r.monetary)) AS avg_spend
FROM hh_rfm r JOIN recip USING (household_key)
LEFT JOIN red d USING (household_key)
GROUP BY 1 ORDER BY 1
""").fetchdf().to_string(index=False))
print(con.execute("""
WITH recip AS (SELECT DISTINCT household_key FROM campaign_table),
     ranked AS (SELECT r.household_key, PERCENT_RANK() OVER (ORDER BY r.monetary) AS m_pctile
                FROM hh_rfm r JOIN recip USING (household_key)),
     red AS (SELECT DISTINCT household_key FROM coupon_redempt)
SELECT '상환 434가구의 수신 가구 내 지출 백분위' AS metric,
       ROUND(100 * QUANTILE_CONT(m_pctile, 0.25)) AS p25,
       ROUND(100 * MEDIAN(m_pctile)) AS med,
       ROUND(100 * QUANTILE_CONT(m_pctile, 0.75)) AS p75
FROM ranked JOIN red USING (household_key)
""").fetchdf().to_string(index=False))

# ── 3. 매칭 사전-사후 설계 ──
con.execute("""
CREATE OR REPLACE TEMP VIEW hh_day AS
SELECT household_key, DAY, SUM(SALES_VALUE) AS spend
FROM transactions_base GROUP BY 1, 2
""")
con.execute("""
CREATE OR REPLACE TEMP TABLE pairs AS
SELECT DISTINCT ct.household_key, ct.CAMPAIGN, cd.DESCRIPTION AS camp_type,
       cd.START_DAY AS s, cd.END_DAY AS e
FROM campaign_table ct JOIN campaign_desc cd USING (CAMPAIGN)
""")

# 깨끗한 수신 쌍: 전후 60일 창이 관측 안이고, 그 가구의 다른 수신 캠페인과 안 겹침
con.execute(f"""
CREATE OR REPLACE TEMP TABLE r_spend AS
SELECT p.household_key, p.CAMPAIGN, p.camp_type,
       COALESCE(SUM(CASE WHEN d.DAY BETWEEN p.s - {W} AND p.s - 1 THEN d.spend END), 0) AS pre_spend,
       COALESCE(SUM(CASE WHEN d.DAY BETWEEN p.s AND p.s + {W} - 1 THEN d.spend END), 0) AS post_spend
FROM pairs p
LEFT JOIN hh_day d ON d.household_key = p.household_key
                  AND d.DAY BETWEEN p.s - {W} AND p.s + {W} - 1
WHERE p.s - {W} >= 1 AND p.s + {W} - 1 <= 711
  AND NOT EXISTS (SELECT 1 FROM pairs o
                  WHERE o.household_key = p.household_key AND o.CAMPAIGN != p.CAMPAIGN
                    AND o.s <= p.s + {W} - 1 AND o.e >= p.s - {W})
GROUP BY 1, 2, 3
""")
print("\n### [3단계] 겹침 없는 '깨끗한' 수신 쌍 — 타입별 생존 규모")
print(con.execute("""
WITH per_camp AS (
    SELECT cd.DESCRIPTION AS camp_type, cd.CAMPAIGN, COUNT(r.CAMPAIGN) AS cnt
    FROM campaign_desc cd LEFT JOIN r_spend r USING (CAMPAIGN)
    GROUP BY 1, 2)
SELECT camp_type, COUNT(*) AS n_campaigns, SUM(cnt) AS clean_pairs,
       CAST(MEDIAN(cnt) AS INT) AS pairs_med_per_campaign
FROM per_camp GROUP BY 1 ORDER BY 1
""").fetchdf().to_string(index=False))
print("→ 전체 7,208쌍 중 1,326쌍(18.4%)만 생존. TypeB·C는 캠페인 단위 표본이 얇아 타입 단위로만 서술")

# 비교군 풀: 미수신 916가구 ∪ 아직 안 받은 미래 수신 가구 (같은 창 지출 집계)
con.execute(f"""
CREATE OR REPLACE TEMP TABLE pool AS
SELECT c.CAMPAIGN, nr.household_key,
       COALESCE(SUM(CASE WHEN d.DAY BETWEEN c.s - {W} AND c.s - 1 THEN d.spend END), 0) AS pre_spend,
       COALESCE(SUM(CASE WHEN d.DAY BETWEEN c.s AND c.s + {W} - 1 THEN d.spend END), 0) AS post_spend
FROM (SELECT DISTINCT CAMPAIGN, s FROM pairs WHERE s - {W} >= 1 AND s + {W} - 1 <= 711) c
JOIN (
    SELECT household_key, NULL AS first_recv FROM hh_rfm
    WHERE household_key NOT IN (SELECT DISTINCT household_key FROM campaign_table)
    UNION ALL
    SELECT household_key, MIN(s) FROM pairs GROUP BY 1
) nr ON nr.first_recv IS NULL OR nr.first_recv > c.s + {W} - 1
LEFT JOIN hh_day d ON d.household_key = nr.household_key
                  AND d.DAY BETWEEN c.s - {W} AND c.s + {W} - 1
GROUP BY 1, 2
""")

# 가구 내 변화량(주간) − 매칭 비교군(같은 캠페인, pre 지출 ±30%)의 평균 변화량
con.execute(f"""
CREATE OR REPLACE TEMP TABLE did AS
SELECT r.camp_type, rfm.segment,
       (r.post_spend - r.pre_spend) * 7.0 / {W}
       - (SELECT AVG((k.post_spend - k.pre_spend) * 7.0 / {W}) FROM pool k
          WHERE k.CAMPAIGN = r.CAMPAIGN
            AND ABS(k.pre_spend - r.pre_spend) <= GREATEST({CALIPER} * r.pre_spend, {FLOOR}))
       AS did_wk
FROM r_spend r JOIN hh_rfm rfm USING (household_key)
""")
mc = con.execute("SELECT ROUND(100.0*AVG(CASE WHEN did_wk IS NOT NULL THEN 1 ELSE 0 END),1) FROM did").fetchone()[0]
print(f"\n### [3단계] 매칭 사전-사후 차이 — 타입 단위 (매칭 커버리지 {mc}%)")
print(con.execute("""
SELECT camp_type, COUNT(*) AS n,
       ROUND(AVG(did_wk), 2) AS did_wk, ROUND(MEDIAN(did_wk), 2) AS did_wk_med,
       ROUND(100.0 * AVG(CASE WHEN did_wk > 0 THEN 1 ELSE 0 END), 1) AS pct_above_ctrl
FROM did WHERE did_wk IS NOT NULL
GROUP BY 1 ORDER BY 1
""").fetchdf().to_string(index=False))

# ── 4. 세그먼트 분해 (심슨의 역설 체크) ──
print("\n### [4단계] 같은 차이를 세그먼트로 분해 — 부호가 갈린다")
did_df = con.execute("""
SELECT camp_type, segment, COUNT(*) AS n,
       ROUND(AVG(did_wk), 2) AS did_wk, ROUND(MEDIAN(did_wk), 2) AS did_wk_med,
       ROUND(100.0 * AVG(CASE WHEN did_wk > 0 THEN 1 ELSE 0 END), 1) AS pct_above_ctrl
FROM did WHERE did_wk IS NOT NULL
GROUP BY 1, 2 ORDER BY 1, 2
""").fetchdf()
print(did_df.to_string(index=False))

flips = did_df[(did_df["n"] >= 30) & (did_df["did_wk"] < 0)]
print(f"\n부호 뒤집힘(n>=30 셀 중 DID<0): {len(flips)}건 → 타입 단위 평균 인용 금지"
      + ("" if flips.empty else "\n" + flips.to_string(index=False)))

con.close()
print("\n03_campaign_effect done")
