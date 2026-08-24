# 비즈니스 질문: 전 기간(711일) 기준 RFM 세그먼트가 "최근 1년(DAY 348~711)"만으로 다시 매기면
#   얼마나 달라지는가? (좌측 절단·램프인이 세그먼트를 왜곡하는지 — 고정 창 보완 체크)
# 가정한 의사결정: 본분석·권고안의 타겟 리스트를 전 기간 RFM으로 갈지, 최근 창 RFM으로 갈지
# 판정 기준: 세그먼트 유지율이 80% 미만이면 전 기간 RFM 단독 사용 금지, 최근 창 기준 병행
# 설계 주의: 분류 규칙은 q01과 동일 논리(고액 = M 중앙값 초과, 활성 = R 중앙값 이하)를
#   최근 창 내 분포로 다시 적용. 창 내 0방문 가구는 별도 분류('창내 무활동').
import duckdb
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "processed" / "dunnhumby.duckdb"
con = duckdb.connect(str(DB))
START = 348  # 711 - 364 + 1: 최근 52주

con.execute(f"""
CREATE OR REPLACE TEMP TABLE recent AS
WITH win AS (
    SELECT household_key,
           SUM(SALES_VALUE) AS m_recent,
           711 - MAX(DAY) AS r_recent
    FROM transactions_base WHERE DAY >= {START}
    GROUP BY 1
),
med AS (SELECT MEDIAN(m_recent) AS m_med, MEDIAN(r_recent) AS r_med FROM win)
SELECT w.household_key,
       CASE WHEN w.m_recent > med.m_med THEN '고액' ELSE '저액' END ||
       CASE WHEN w.r_recent <= med.r_med THEN '활성' ELSE '휴면' END AS seg_recent
FROM win w, med
""")

print("### 전 기간 세그먼트 × 최근 1년 세그먼트 교차표 (가구수)")
print(con.execute("""
SELECT rfm.segment AS seg_full,
       COALESCE(r.seg_recent, '창내 무활동') AS seg_recent,
       COUNT(*) AS n_hh
FROM hh_rfm rfm LEFT JOIN recent r USING (household_key)
GROUP BY 1, 2 ORDER BY 1, 3 DESC
""").fetchdf().to_string(index=False))

print("\n### 요약: 전 기간 세그먼트별 '같은 등급 유지' 비율")
print(con.execute("""
WITH cmp AS (
    SELECT rfm.segment AS seg_full,
           COALESCE(r.seg_recent, '창내무활동') AS seg_recent,
           -- q01 명명과 등급 매칭: S1=고액활성, S2=고액휴면, S3=저액활성, S4=저액휴면
           CASE rfm.segment
               WHEN 'S1_고액활성' THEN '고액활성' WHEN 'S2_고액휴면' THEN '고액휴면'
               WHEN 'S3_저액활성' THEN '저액활성' WHEN 'S4_저액휴면' THEN '저액휴면'
           END AS grade_full
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

con.close()
print("\nq07 done")
