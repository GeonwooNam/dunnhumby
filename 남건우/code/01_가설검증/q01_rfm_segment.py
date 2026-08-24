# 비즈니스 질문: 예산 삭감 권고안의 1차 축으로 쓸 가구 세그먼트가 RFM으로 의미 있게 갈리는가?
# 가정한 의사결정: 쿠폰·캠페인 예산 30% 삭감 시 유지/삭감 대상을 나누는 기준 축으로 RFM 채택 여부
# 판정 기준: 세그먼트 간 (a)지출 규모·매출 기여 (b)할인 의존도 (c)캠페인 수신·상환률이 실질적으로
#            갈리면 채택. 안 갈리면 다른 축(할인 의존도 단독 등)으로 교체.
# 산출: dunnhumby.duckdb에 hh_rfm 테이블 저장 (q03·q04에서 재사용)
import duckdb
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "processed" / "dunnhumby.duckdb"
con = duckdb.connect(str(DB))

con.execute("""
CREATE OR REPLACE TABLE hh_rfm AS
WITH hh AS (
    SELECT household_key,
           711 - MAX(DAY)                      AS recency,
           COUNT(DISTINCT DAY)                 AS freq,
           SUM(SALES_VALUE)                    AS monetary,
           SUM(DISCOUNT_AMOUNT) / NULLIF(SUM(GROSS_SALES), 0) AS discount_reliance
    FROM transactions_base GROUP BY 1
), scored AS (
    SELECT *,
           NTILE(4) OVER (ORDER BY recency DESC) AS r_score,  -- 4 = 최근
           NTILE(4) OVER (ORDER BY freq)         AS f_score,  -- 4 = 자주
           NTILE(4) OVER (ORDER BY monetary)     AS m_score   -- 4 = 고액
    FROM hh
)
SELECT *,
       CASE WHEN m_score >= 3 AND r_score >= 3 THEN 'S1_고액활성'
            WHEN m_score >= 3 AND r_score <= 2 THEN 'S2_고액휴면'
            WHEN m_score <= 2 AND r_score >= 3 THEN 'S3_저액활성'
            ELSE 'S4_저액휴면' END AS segment
FROM scored
""")

# 조인 검증 (규칙 6): hh_rfm 2,500행 유지 확인
n = con.execute("SELECT COUNT(*) FROM hh_rfm").fetchone()[0]
assert n == 2500, f"hh_rfm rows = {n} (expected 2500)"
print(f"hh_rfm 생성: {n:,} 가구 (조인 전후 행수 불변 확인)")

print("\n### 세그먼트 프로필 (판정 기준 a·b·c)")
print(con.execute("""
WITH camp AS (SELECT DISTINCT household_key FROM campaign_table),
     red  AS (SELECT DISTINCT household_key FROM coupon_redempt),
     demo AS (SELECT DISTINCT household_key FROM hh_demographic)
SELECT r.segment,
       COUNT(*)                                          AS n_hh,
       ROUND(AVG(r.monetary))                            AS avg_spend,
       ROUND(100.0 * SUM(r.monetary) / (SELECT SUM(monetary) FROM hh_rfm), 1) AS spend_share_pct,
       ROUND(AVG(r.freq))                                AS avg_visit_days,
       ROUND(AVG(r.recency))                             AS avg_recency_days,
       ROUND(100.0 * AVG(r.discount_reliance), 1)        AS avg_disc_reliance_pct,
       ROUND(100.0 * AVG(CASE WHEN c.household_key IS NOT NULL THEN 1 ELSE 0 END), 1) AS campaign_recv_pct,
       ROUND(100.0 * AVG(CASE WHEN d.household_key IS NOT NULL THEN 1 ELSE 0 END), 1) AS redeem_pct,
       ROUND(100.0 * AVG(CASE WHEN dm.household_key IS NOT NULL THEN 1 ELSE 0 END), 1) AS demo_pct
FROM hh_rfm r
LEFT JOIN camp c USING (household_key)
LEFT JOIN red  d USING (household_key)
LEFT JOIN demo dm USING (household_key)
GROUP BY 1 ORDER BY 1
""").fetchdf().to_string(index=False))

print("\n### 세그먼트 내 할인 의존도 분포 (동질성 확인)")
print(con.execute("""
SELECT segment,
       ROUND(100*QUANTILE_CONT(discount_reliance, 0.25), 1) AS p25,
       ROUND(100*MEDIAN(discount_reliance), 1)              AS med,
       ROUND(100*QUANTILE_CONT(discount_reliance, 0.75), 1) AS p75
FROM hh_rfm GROUP BY 1 ORDER BY 1
""").fetchdf().to_string(index=False))

con.close()
print("\nq01 done")
