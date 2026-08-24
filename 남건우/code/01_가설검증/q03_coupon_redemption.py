# 비즈니스 질문: 쿠폰 상환은 어떤 가구에 집중되는가 — 상환 가구는 애초에 고액 구매 가구인가?
# 가정한 의사결정: 예산 삭감 권고에서 "상환률 높은 세그먼트 유지" 논리를 쓸 수 있는지 판단.
#   상환이 고액 가구에 쏠려 있으면 "원래 살 사람에게 준 쿠폰" 가능성을 병기해야 한다.
# 판정 기준: 세그먼트별 상환률 격차가 크고, 상환 가구의 M(지출)이 같은 수신 가구 중 비상환
#   가구보다 뚜렷이 위면 → 상환률 단독을 근거로 쓰지 않고 타겟팅 편향 주석과 함께 사용.
# 주의(규칙 4·6): 상환-지출 관계는 "연관"으로만 서술. coupon 테이블 조인 없음(다대다 회피) —
#   상환은 가구×캠페인 수준에서만 본다.
import duckdb
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "processed" / "dunnhumby.duckdb"
con = duckdb.connect(str(DB))

print("### 세그먼트별 수신·상환 (분모 = 캠페인 수신 가구)")
print(con.execute("""
WITH recip AS (SELECT DISTINCT household_key FROM campaign_table),
     red   AS (SELECT household_key, COUNT(*) AS n_redempt FROM coupon_redempt GROUP BY 1)
SELECT r.segment,
       COUNT(*) AS recipients,
       SUM(CASE WHEN d.household_key IS NOT NULL THEN 1 ELSE 0 END) AS redeemers,
       ROUND(100.0 * SUM(CASE WHEN d.household_key IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) AS redeem_rate_pct,
       ROUND(AVG(CASE WHEN d.household_key IS NOT NULL THEN d.n_redempt END), 1) AS redempt_per_redeemer
FROM hh_rfm r JOIN recip USING (household_key)
LEFT JOIN red d USING (household_key)
GROUP BY 1 ORDER BY 1
""").fetchdf().to_string(index=False))

print("\n### 수신 가구 내 상환 vs 비상환 가구의 지출 비교 (연관 확인)")
print(con.execute("""
WITH recip AS (SELECT DISTINCT household_key FROM campaign_table),
     red   AS (SELECT DISTINCT household_key FROM coupon_redempt)
SELECT CASE WHEN d.household_key IS NOT NULL THEN '상환' ELSE '비상환' END AS grp,
       COUNT(*) AS n_hh,
       ROUND(MEDIAN(r.monetary)) AS med_spend,
       ROUND(AVG(r.monetary)) AS avg_spend,
       ROUND(AVG(r.freq)) AS avg_visit_days,
       ROUND(100 * AVG(r.discount_reliance), 1) AS disc_reliance_pct
FROM hh_rfm r JOIN recip USING (household_key)
LEFT JOIN red d USING (household_key)
GROUP BY 1 ORDER BY 1
""").fetchdf().to_string(index=False))

print("\n### 캠페인 타입별 상환률 (분모 = 해당 타입 수신 가구×캠페인 쌍)")
print(con.execute("""
WITH pairs AS (
    SELECT DISTINCT ct.household_key, ct.CAMPAIGN, cd.DESCRIPTION AS camp_type
    FROM campaign_table ct JOIN campaign_desc cd USING (CAMPAIGN)),
red AS (SELECT DISTINCT household_key, CAMPAIGN FROM coupon_redempt)
SELECT p.camp_type,
       COUNT(*) AS recv_pairs,
       SUM(CASE WHEN r.household_key IS NOT NULL THEN 1 ELSE 0 END) AS redeemed_pairs,
       ROUND(100.0 * SUM(CASE WHEN r.household_key IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) AS redeem_rate_pct
FROM pairs p LEFT JOIN red r USING (household_key, CAMPAIGN)
GROUP BY 1 ORDER BY 1
""").fetchdf().to_string(index=False))

print("\n### 상환 가구의 M 위치 (수신 가구 내 지출 백분위)")
print(con.execute("""
WITH recip AS (SELECT DISTINCT household_key FROM campaign_table),
     ranked AS (
        SELECT r.household_key, PERCENT_RANK() OVER (ORDER BY r.monetary) AS m_pctile
        FROM hh_rfm r JOIN recip USING (household_key)),
     red AS (SELECT DISTINCT household_key FROM coupon_redempt)
SELECT ROUND(100 * QUANTILE_CONT(m_pctile, 0.25), 0) AS p25,
       ROUND(100 * MEDIAN(m_pctile), 0) AS med,
       ROUND(100 * QUANTILE_CONT(m_pctile, 0.75), 0) AS p75
FROM ranked JOIN red USING (household_key)
""").fetchdf().to_string(index=False))

con.close()
print("\nq03 done")
