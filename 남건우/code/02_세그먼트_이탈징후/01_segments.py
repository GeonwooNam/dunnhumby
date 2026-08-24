# [출발점] 가구 세그먼트 축 — 2x2 (지출 M × 최근성 R)
# 질문 1: 예산 권고의 1차 축으로 쓸 세그먼트가 M×R로 의미 있게 갈리는가?
# 질문 2: 전 기간(711일) 기준 세그먼트를 최근 1년으로 재산정하면 얼마나 달라지는가? (안정성)
# 판정: (1) 세그먼트 간 지출·수신·상환이 수 배씩 갈리면 채택
#       (2) 등급 유지율 80% 미만이면 전 기간 기준 단독 사용 금지
# 산출: dunnhumby.duckdb에 hh_rfm 테이블 저장 — 02·03 스크립트가 재사용하므로 가장 먼저 실행
import duckdb
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "processed" / "dunnhumby.duckdb"
con = duckdb.connect(str(DB))

# ── 1. 전 기간 RFM + 세그먼트 (고액 = M 상위 절반, 활성 = R 상위 절반) ──
con.execute("""
CREATE OR REPLACE TABLE hh_rfm AS
WITH hh AS (
    SELECT household_key,
           711 - MAX(DAY)      AS recency,
           COUNT(DISTINCT DAY) AS freq,
           SUM(SALES_VALUE)    AS monetary,
           -- 세그먼트 축 후보였다가 탈락(전 세그먼트 ~16%로 동일). 호환 위해 컬럼만 유지
           SUM(DISCOUNT_AMOUNT) / NULLIF(SUM(GROSS_SALES), 0) AS discount_reliance
    FROM transactions_base GROUP BY 1
), scored AS (
    SELECT *,
           -- household_key 타이브레이커: 동률 시에도 실행마다 같은 결과가 나오게 고정
           NTILE(4) OVER (ORDER BY recency DESC, household_key) AS r_score,  -- 4 = 최근
           NTILE(4) OVER (ORDER BY freq, household_key)         AS f_score,  -- 4 = 자주
           NTILE(4) OVER (ORDER BY monetary, household_key)     AS m_score   -- 4 = 고액
    FROM hh
)
SELECT *,
       CASE WHEN m_score >= 3 AND r_score >= 3 THEN 'S1_고액활성'
            WHEN m_score >= 3 AND r_score <= 2 THEN 'S2_고액휴면'
            WHEN m_score <= 2 AND r_score >= 3 THEN 'S3_저액활성'
            ELSE 'S4_저액휴면' END AS segment
FROM scored
""")
n = con.execute("SELECT COUNT(*) FROM hh_rfm").fetchone()[0]
assert n == 2500, f"hh_rfm rows = {n} (expected 2500)"
print(f"hh_rfm 생성: {n:,} 가구")

print("\n### 세그먼트 프로필 — 지출·매출 기여·캠페인 수신·쿠폰 상환")
print(con.execute("""
WITH camp AS (SELECT DISTINCT household_key FROM campaign_table),
     red  AS (SELECT DISTINCT household_key FROM coupon_redempt)
SELECT r.segment,
       COUNT(*)                AS n_hh,
       ROUND(AVG(r.monetary))  AS avg_spend,
       ROUND(100.0 * SUM(r.monetary) / (SELECT SUM(monetary) FROM hh_rfm), 1) AS spend_share_pct,
       ROUND(AVG(r.freq))      AS avg_visit_days,
       ROUND(100.0 * AVG(CASE WHEN c.household_key IS NOT NULL THEN 1 ELSE 0 END), 1) AS campaign_recv_pct,
       ROUND(100.0 * AVG(CASE WHEN d.household_key IS NOT NULL THEN 1 ELSE 0 END), 1) AS redeem_pct
FROM hh_rfm r
LEFT JOIN camp c USING (household_key)
LEFT JOIN red  d USING (household_key)
GROUP BY 1 ORDER BY 1
""").fetchdf().to_string(index=False))

# ── 2. 안정성 체크: 최근 1년(DAY 348~711) 창으로 재산정 ──
START = 348
con.execute(f"""
CREATE OR REPLACE TEMP TABLE recent AS
WITH win AS (
    SELECT household_key, SUM(SALES_VALUE) AS m_recent, 711 - MAX(DAY) AS r_recent
    FROM transactions_base WHERE DAY >= {START}
    GROUP BY 1
),
med AS (SELECT MEDIAN(m_recent) AS m_med, MEDIAN(r_recent) AS r_med FROM win)
SELECT w.household_key,
       CASE WHEN w.m_recent > med.m_med THEN '고액' ELSE '저액' END ||
       CASE WHEN w.r_recent <= med.r_med THEN '활성' ELSE '휴면' END AS seg_recent
FROM win w, med
""")

print("\n### 전 기간 세그먼트별 '최근 1년 기준 같은 등급 유지' 비율")
print(con.execute("""
WITH cmp AS (
    SELECT rfm.segment AS seg_full,
           COALESCE(r.seg_recent, '창내무활동') AS seg_recent,
           SUBSTR(rfm.segment, 4) AS grade_full   -- 'S1_고액활성' → '고액활성'
    FROM hh_rfm rfm LEFT JOIN recent r USING (household_key))
SELECT seg_full, COUNT(*) AS n_hh,
       ROUND(100.0 * AVG(CASE WHEN seg_recent = grade_full THEN 1 ELSE 0 END), 1) AS same_pct,
       ROUND(100.0 * AVG(CASE WHEN seg_recent = '창내무활동' THEN 1 ELSE 0 END), 1) AS gone_pct
FROM cmp GROUP BY 1
UNION ALL
SELECT '전체', COUNT(*),
       ROUND(100.0 * AVG(CASE WHEN seg_recent = grade_full THEN 1 ELSE 0 END), 1),
       ROUND(100.0 * AVG(CASE WHEN seg_recent = '창내무활동' THEN 1 ELSE 0 END), 1)
FROM cmp ORDER BY 1
""").fetchdf().to_string(index=False))

print("\n### S2 고액휴면의 이동 방향 (갈림길 확인)")
print(con.execute("""
SELECT COALESCE(r.seg_recent, '창내 무활동') AS seg_recent, COUNT(*) AS n_hh
FROM hh_rfm rfm LEFT JOIN recent r USING (household_key)
WHERE rfm.segment = 'S2_고액휴면'
GROUP BY 1 ORDER BY 2 DESC
""").fetchdf().to_string(index=False))

con.close()
print("\n01_segments done")
