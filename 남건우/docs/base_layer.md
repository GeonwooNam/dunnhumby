# base_layer.md — 1단계 베이스 레이어 (제외 규칙 + 검증 결과)

- 빌드일: 2026-07-23 · 스크립트: `sql/build_base_layer.py` (재실행으로 전체 재현 가능)
- 산출: `data/processed/dunnhumby.duckdb`
  - raw 8개 테이블 원본 그대로 + **transactions_base** (2,551,768행)
- **이후 모든 분석은 transactions_base만 사용한다. raw 직접 집계 금지.**

## 제외 규칙 (우선순위 순 적용, 상호 배타)

| 규칙 | 대상 | 행수 | 매출 | 근거 |
|---|---|---:|---:|---|
| E1_qty_zero | QUANTITY = 0 | 14,466 | $19 | 99.5%는 SALES_VALUE도 0. 소액 할인 조정 기록으로 추정 |
| E2_nonproduct | COMMODITY 'COUPON/MISC ITEMS' | 27,710 | $639,878 | KIOSK-GAS(73%)·MISC SALES TRAN 소속 — 상품 구매가 아님. 수량 단위 비교 불가(최대 89,638) |
| E3_fuel | COMMODITY 'FUEL' | 1,788 | $29,537 | 수량이 연료 부피 단위(최대 30,080) |
| **제외 합계** | | **43,964 (1.7%)** | **$669,434 (8.31%)** | |

보정 규칙 F1: 양수 RETAIL_DISC 36행(데이터 오류, 최대 $3.99)은 행을 버리지 않고 **0으로 클램프**.

**해석상 중요:** 제외 매출의 96%가 주유 키오스크·잡수입이다. 따라서 transactions_base의
매출(net_spend)은 **"식료품 상품 매출"**이며, 가구 총지출을 말할 때 주유가 빠져 있음을 병기할 것.

## 파생 컬럼

- `GROSS_SALES` = SALES_VALUE − RETAIL_DISC(클램프 후) − COUPON_MATCH_DISC (정가 매출, metrics.md)
- `DISCOUNT_AMOUNT` = −(RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC) (양수 할인액)

## sanity check 결과 (규칙 7 — 빌드 시 자동 실행, 2026-07-23 실행 기준)

1. PASS — 행수 회계: raw 2,595,732 = base 2,551,768 + 제외 43,964
2. PASS — 매출 회계: raw $8,057,463.08 = base $7,388,028.78 + 제외 $669,434.30
3. PASS — 기간 커버리지 유지: DAY 1~711, WEEK 1~102
4. PASS — 가구 보존: 2,500 → 2,500 (전량 제외된 가구 없음)
5. PASS — RETAIL_DISC 클램프: 양수 잔존 0행

## 한계

여기까지는 거래 정제만 다뤘다. coupon(다대다)·causal_data(매장 115개 부분 커버)는 정제 대상이
아니라 원본 그대로 적재했으므로, 이 테이블들을 쓰는 분석은 각자 조인 전 축약과 커버리지 명시가
필요하다 (`docs/data_notes.md` 6·7번 항목).
