# 비즈니스 질문: q02의 매칭 사전-사후 차이(TypeA +$3.11/주)가 세그먼트별로 쪼개도 유지되는가,
#   아니면 특정 세그먼트가 끌어올린 값인가? (심슨의 역설 체크)
# 가정한 의사결정: 예산 삭감 권고를 "타입 단위"로 낼지 "타입×세그먼트 단위"로 낼지
# 판정 기준: 세그먼트 분해 시 DID 부호가 뒤집히는 셀이 있으면 타입 단위 평균 인용 금지,
#   셀별 서술로 전환. n<30 셀은 판정 유보.
# 설계 주의: q02와 동일한 매칭(캘리퍼 ±30%, 하한 $25, 풀 B). 산출은 "차이"이지 "효과" 아님.
#   세그먼트는 전 기간 RFM(hh_rfm) 기준 — 창 시점의 상태가 아니라는 한계를 병기.
import duckdb
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "processed" / "dunnhumby.duckdb"
con = duckdb.connect(str(DB))
W = 60
CALIPER = 0.30
FLOOR = 25.0

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
con.execute(f"""
CREATE OR REPLACE TEMP TABLE r_spend AS
SELECT p.household_key, p.CAMPAIGN, p.camp_type, p.s,
       COALESCE(SUM(CASE WHEN d.DAY BETWEEN p.s - {W} AND p.s - 1 THEN d.spend END), 0) AS pre_spend,
       COALESCE(SUM(CASE WHEN d.DAY BETWEEN p.s AND p.s + {W} - 1 THEN d.spend END), 0) AS post_spend
FROM pairs p
LEFT JOIN hh_day d ON d.household_key = p.household_key
                  AND d.DAY BETWEEN p.s - {W} AND p.s + {W} - 1
WHERE p.s - {W} >= 1 AND p.s + {W} - 1 <= 711
  AND NOT EXISTS (SELECT 1 FROM pairs o
                  WHERE o.household_key = p.household_key AND o.CAMPAIGN != p.CAMPAIGN
                    AND o.s <= p.s + {W} - 1 AND o.e >= p.s - {W})
GROUP BY 1, 2, 3, 4
""")
con.execute(f"""
CREATE OR REPLACE TEMP TABLE pool AS
SELECT c.CAMPAIGN, c.s, nr.household_key,
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
GROUP BY 1, 2, 3
""")

print("### 매칭 DID의 타입×세그먼트 분해 (풀 B, 주간 지출, '차이'이지 '효과' 아님)")
did_df = con.execute(f"""
WITH did AS (
    SELECT r.camp_type, rfm.segment, r.household_key,
           (r.post_spend - r.pre_spend) * 7.0 / {W} AS delta_r,
           (SELECT AVG((k.post_spend - k.pre_spend) * 7.0 / {W}) FROM pool k
            WHERE k.CAMPAIGN = r.CAMPAIGN
              AND ABS(k.pre_spend - r.pre_spend) <= GREATEST({CALIPER} * r.pre_spend, {FLOOR})) AS delta_c
    FROM r_spend r JOIN hh_rfm rfm USING (household_key))
SELECT camp_type, segment, COUNT(*) AS n,
       ROUND(AVG(delta_r - delta_c), 2) AS did_wk,
       ROUND(MEDIAN(delta_r - delta_c), 2) AS did_wk_med,
       ROUND(100.0 * AVG(CASE WHEN delta_r > delta_c THEN 1 ELSE 0 END), 1) AS pct_above_ctrl
FROM did WHERE delta_c IS NOT NULL
GROUP BY 1, 2 ORDER BY 1, 2
""").fetchdf()
print(did_df.to_string(index=False))

flips = did_df[(did_df["n"] >= 30) & (did_df["did_wk"] < 0)]
print(f"\n부호 뒤집힘(n>=30 셀 중 DID<0): {len(flips)}건"
      + ("" if flips.empty else "\n" + flips.to_string(index=False)))

con.close()
print("\nq06 done")
