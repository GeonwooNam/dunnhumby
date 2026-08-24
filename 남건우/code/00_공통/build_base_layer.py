# 1단계 — 베이스 레이어 빌드
# 산출: data/processed/dunnhumby.duckdb
#   - raw 8개 테이블 (원본 그대로 적재)
#   - transactions_base: 정제된 거래 뷰 (이후 모든 분석은 이것만 사용)
# 제외 규칙 근거와 sanity check 결과는 docs/base_layer.md에 기록.
import duckdb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "processed" / "dunnhumby.duckdb"

con = duckdb.connect(str(DB))

RAW_TABLES = ["transaction_data", "product", "hh_demographic", "campaign_table",
              "campaign_desc", "coupon", "coupon_redempt", "causal_data"]

print("[1/4] raw 테이블 적재")
for t in RAW_TABLES:
    con.execute(f"CREATE OR REPLACE TABLE {t} AS SELECT * FROM read_csv_auto('{RAW}/{t}.csv')")
    n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t:20s} {n:>12,d} rows")

print("[2/4] 행 분류 (제외 규칙 E1~E3, 우선순위 순)")
# E1 qty_zero    : QUANTITY = 0            — 매출 합계 $19, 99.5%는 SALES_VALUE도 0
# E2 nonproduct  : COUPON/MISC ITEMS 커모디티 — KIOSK-GAS·MISC SALES TRAN, 수량 단위 비교 불가
# E3 fuel        : FUEL 커모디티            — 수량이 연료 부피 단위
con.execute("""
    CREATE OR REPLACE VIEW _tx_classified AS
    SELECT t.*,
           CASE WHEN t.QUANTITY = 0 THEN 'E1_qty_zero'
                WHEN p.COMMODITY_DESC = 'COUPON/MISC ITEMS' THEN 'E2_nonproduct'
                WHEN p.COMMODITY_DESC = 'FUEL' THEN 'E3_fuel'
                ELSE 'keep' END AS row_class
    FROM transaction_data t
    JOIN product p USING (PRODUCT_ID)
""")
acct = con.execute("""
    SELECT row_class, COUNT(*) n_rows, ROUND(SUM(SALES_VALUE), 2) sales_sum
    FROM _tx_classified GROUP BY 1 ORDER BY 1
""").fetchdf()
print(acct.to_string(index=False))

print("[3/4] transactions_base 생성 (F1: 양수 RETAIL_DISC → 0 클램프, 파생 컬럼 추가)")
con.execute("""
    CREATE OR REPLACE TABLE transactions_base AS
    SELECT household_key, BASKET_ID, DAY, WEEK_NO, TRANS_TIME, STORE_ID, PRODUCT_ID,
           QUANTITY, SALES_VALUE,
           LEAST(RETAIL_DISC, 0) AS RETAIL_DISC,
           COUPON_DISC, COUPON_MATCH_DISC,
           SALES_VALUE - LEAST(RETAIL_DISC, 0) - COUPON_MATCH_DISC AS GROSS_SALES,
           -(LEAST(RETAIL_DISC, 0) + COUPON_DISC + COUPON_MATCH_DISC) AS DISCOUNT_AMOUNT
    FROM _tx_classified WHERE row_class = 'keep'
""")

print("[4/4] sanity checks (CLAUDE.md 규칙 7 — 최소 3개)")
raw_n, raw_sales = con.execute(
    "SELECT COUNT(*), ROUND(SUM(SALES_VALUE),2) FROM transaction_data").fetchone()
base_n, base_sales = con.execute(
    "SELECT COUNT(*), ROUND(SUM(SALES_VALUE),2) FROM transactions_base").fetchone()
excl_n, excl_sales = con.execute(
    "SELECT COUNT(*), ROUND(SUM(SALES_VALUE),2) FROM _tx_classified WHERE row_class != 'keep'").fetchone()

# 1) 행수 회계: raw = base + 제외
ok1 = raw_n == base_n + excl_n
print(f"  [{'PASS' if ok1 else 'FAIL'}] 행수 회계: raw {raw_n:,} = base {base_n:,} + 제외 {excl_n:,}")
# 2) 매출 회계: raw 합 = base 합 + 제외 합 (센트 반올림 오차 1달러 허용)
ok2 = abs(raw_sales - (base_sales + excl_sales)) < 1.0
print(f"  [{'PASS' if ok2 else 'FAIL'}] 매출 회계: raw {raw_sales:,.2f} = base {base_sales:,.2f} + 제외 {excl_sales:,.2f}"
      f" (제외 비중 {100*excl_sales/raw_sales:.2f}%)")
# 3) 기간 커버리지 유지: DAY 1~711, WEEK 1~102
d0, d1, w0, w1 = con.execute(
    "SELECT MIN(DAY), MAX(DAY), MIN(WEEK_NO), MAX(WEEK_NO) FROM transactions_base").fetchone()
ok3 = (d0, d1, w0, w1) == (1, 711, 1, 102)
print(f"  [{'PASS' if ok3 else 'FAIL'}] 기간 커버리지: DAY {d0}~{d1}, WEEK {w0}~{w1}")
# 4) 가구 보존: 2,500가구 전원이 base에 남는가
hh_raw = con.execute("SELECT COUNT(DISTINCT household_key) FROM transaction_data").fetchone()[0]
hh_base = con.execute("SELECT COUNT(DISTINCT household_key) FROM transactions_base").fetchone()[0]
ok4 = hh_raw == hh_base
print(f"  [{'PASS' if ok4 else 'WARN'}] 가구 보존: raw {hh_raw:,} → base {hh_base:,}"
      + ("" if ok4 else "  (전량 제외된 가구 존재 — base_layer.md에 기록할 것)"))
# 5) 클램프 확인: base에 양수 RETAIL_DISC가 없는가
pos = con.execute("SELECT COUNT(*) FROM transactions_base WHERE RETAIL_DISC > 0").fetchone()[0]
ok5 = pos == 0
print(f"  [{'PASS' if ok5 else 'FAIL'}] RETAIL_DISC 클램프: 양수 잔존 {pos}행")

con.close()
status = all([ok1, ok2, ok3, ok5])
print(f"\nbase layer build: {'OK' if status else 'FAILED'} → {DB}")
raise SystemExit(0 if status else 1)
