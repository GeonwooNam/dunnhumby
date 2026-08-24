# metrics.md — 지표 정의 (계산 전 정의 선행, CLAUDE.md 규칙 3)

모든 지표는 별도 명시가 없으면 **transactions_base**(1단계 베이스 레이어, 제외 규칙은
`docs/base_layer.md`) 위에서 계산한다. raw 직접 집계 금지.

## 금액 지표

| 지표 | 정의 | 비고 |
|---|---|---|
| **net_spend (매출/지출, 기본)** | SUM(SALES_VALUE) | 고객 지불액(할인 반영 후). 비상품·연료 행 제외 후이므로 "상품 매출"이다 (제외분 = 전체의 약 8.0%) |
| **gross_spend (정가 매출)** | SUM(SALES_VALUE − RETAIL_DISC − COUPON_MATCH_DISC) | 할인 컬럼은 **음수 원값 그대로** 사용 (빼기 = 절댓값 더하기). COUPON_DISC는 제조사 부담이라 정가 재구성에서 제외 |
| **discount_amount (할인액)** | −(RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC) | 양수로 변환해 사용 |
| **discount_reliance (할인 의존도)** | 가구 단위 SUM(discount_amount) / SUM(gross_spend) | 0~1. q01 세그먼트 축 |

어느 분석에서든 "매출"이라고 쓰면 **net_spend**를 뜻한다. gross를 쓰면 매번 명시한다.

## 행동 지표

| 지표 | 정의 | 비고 |
|---|---|---|
| **visit (방문)** | 가구 × DAY 유니크 1건 | 같은 날 복수 바스켓도 방문 1회 |
| **basket (바스켓)** | BASKET_ID 유니크 1건 | |
| **weekly_spend (주간 지출률)** | 창 내 net_spend ÷ (창 일수 / 7) | 길이가 다른 기간을 비교할 때 사용 (q02) |

## RFM (q01, 전 기간 기준)

- **R** = 711 − 가구의 마지막 방문 DAY (작을수록 최근)
- **F** = 전 기간 방문일수 (visit 수)
- **M** = 전 기간 net_spend 합
- 스코어: R/F/M 각각 가구 분포의 4분위로 1~4점 (R은 작을수록 4점). 세그먼트 명명은 q01에서 확정.
- 한계: 전 기간 기준이라 "최근 성향 변화"는 못 잡는다. 좌측 절단(관측 초기 램프인) 때문에
  F·M은 관측 기간 내 활동량이지 고객 생애 규모가 아니다.

## 캠페인 사전-사후 (q02)

- **pre 창** = [START_DAY − 60, START_DAY − 1], **post 창** = [START_DAY, START_DAY + 59]
- **깨끗한 캠페인×가구 쌍** = 해당 가구가 받은 **다른** 캠페인의 활성 기간 [START_DAY, END_DAY]이
  pre·post 창과 하루도 겹치지 않는 쌍. (오염원은 그 가구가 실제 받은 캠페인만으로 정의.
  매장 단위 진열·전단 오염은 통제 불가 — 한계로 명시)
- 비교 지표: post weekly_spend − pre weekly_spend (가구 내 변화량)
- 판정 지표(파일럿 게이트): 깨끗한 쌍 수, 그리고 매칭 커버리지 = pre 창 weekly_spend 기준
  캘리퍼(±30%) 안에 비교군 후보가 존재하는 수신 가구 비율

## 말기 비활동 (q04에서 확정, 2026-07-23)

- **정의**: 관측 종료(DAY 711) 기준, 마지막 방문 후 경과일 ≥ max(자기 중앙 구매 간격 × 3, 14일)
- 용어는 "이탈"이 아니라 **"말기 비활동"** — 관측 중단과 진짜 이탈을 구분할 수 없기 때문
  (근거와 민감도 비교는 `reports/q04_churn_definition.md`)
- 방문 1회뿐인 가구(간격 정의 불가, 5가구)는 판정 제외
