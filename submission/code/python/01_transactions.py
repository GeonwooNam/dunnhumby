"""Phase 1 — 거래 데이터 기초 프로파일.

질문: "이 매장의 장사는 어떻게 생겼는가"
  A. 시간축   주차별 매출/바스켓/활성가구 추이 → 계절성, 절단 구간, 분석 기간 확정
  B. 바스켓   바스켓당 금액·품목 수 분포
  C. 상품     DEPARTMENT / COMMODITY 매출 파레토
  D. 매장     매장별 매출 분포, 가구별 주이용매장 집중도

실행: python 01_transactions.py   (차트 → outputs/, 수치 → outputs/01_findings.txt)
"""
import io
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import (AXIS, INK, INK_2, MUTED, OUT_DIR, SEQ, SERIES,
                    load_products, load_transactions, setup_style)

setup_style()
rep = io.StringIO()


def say(*args):
    print(*args, file=rep)


products = load_products()
# 정책 #4 적용본(장보기만) / 원본 둘 다 확보 — 비교 보고용
tx_all = load_transactions(exclude_non_shopping=False)
tx = load_transactions(exclude_non_shopping=True, products=products)

say("=" * 70)
say("Phase 1 — 거래 데이터 기초 프로파일")
say("=" * 70)
say(f"원본 거래           : {len(tx_all):,}행 / 매출 {tx_all.SALES_VALUE.sum():,.0f}")
say(f"장보기만(정책 #4)   : {len(tx):,}행 / 매출 {tx.SALES_VALUE.sum():,.0f} "
    f"(비장보기 제외로 매출 -{(1 - tx.SALES_VALUE.sum() / tx_all.SALES_VALUE.sum()) * 100:.1f}%)")
say(f"가구 {tx.household_key.nunique():,} · 바스켓 {tx.BASKET_ID.nunique():,} · "
    f"상품 {tx.PRODUCT_ID.nunique():,} · 매장 {tx.STORE_ID.nunique():,}")

# ─────────────────────────────────────────────────────────── A. 시간축
say("\n" + "=" * 70)
say("A. 시간축 — 주차별 추이")
say("=" * 70)

wk = tx.groupby("WEEK_NO").agg(
    sales=("SALES_VALUE", "sum"),
    baskets=("BASKET_ID", "nunique"),
    households=("household_key", "nunique"),
    days=("DAY", "nunique"),
    day_min=("DAY", "min"),
    day_max=("DAY", "max"),
)
partial = wk[wk.days < 7]
say(f"주차 범위: {wk.index.min()}~{wk.index.max()} ({len(wk)}주)")
say(f"7일 미만 주차(절단 후보): {list(partial.index)} → days={list(partial.days)}")
med = wk.sales.median()
say(f"주간 매출 중앙값 {med:,.0f} / 최소 {wk.sales.min():,.0f}(W{wk.sales.idxmin()}) "
    f"/ 최대 {wk.sales.max():,.0f}(W{wk.sales.idxmax()})")
say("\n[앞 6주]")
say(wk.head(6)[["sales", "baskets", "households", "days"]].to_string())
say("\n[뒤 6주]")
say(wk.tail(6)[["sales", "baskets", "households", "days"]].to_string())

# 가구 유입/이탈 구조: 가구별 첫/마지막 거래 주차
hh_span = tx.groupby("household_key").WEEK_NO.agg(first_wk="min", last_wk="max")
say(f"\n가구별 첫 거래 주차: W1에 이미 등장 {(hh_span.first_wk == 1).sum():,}가구 "
    f"({(hh_span.first_wk == 1).mean() * 100:.1f}%) / 중앙값 W{hh_span.first_wk.median():.0f}")
say(f"가구별 마지막 거래 주차: 중앙값 W{hh_span.last_wk.median():.0f} / "
    f"마지막 4주(W99+) 이후 거래 없는 가구 {(hh_span.last_wk < 99).sum():,}가구 "
    f"({(hh_span.last_wk < 99).mean() * 100:.1f}%)")
say(f"활성 가구 수: W1 {wk.households.iloc[0]:,} → 중앙값 {wk.households.median():.0f} "
    f"→ 최종주 {wk.households.iloc[-1]:,}")

fig, axes = plt.subplots(3, 1, figsize=(9.5, 7.2), sharex=True)
panels = [("주간 매출", wk.sales, SERIES[0], "{x:,.0f}"),
          ("주간 바스켓 수", wk.baskets, SERIES[1], "{x:,.0f}"),
          ("주간 활성 가구 수", wk.households, SERIES[2], "{x:,.0f}")]
for ax, (title, s, color, fmt) in zip(axes, panels):
    ax.plot(s.index, s.values, color=color, linewidth=2)
    ax.set_title(title)
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.StrMethodFormatter(fmt))
    ax.set_ylim(0, s.max() * 1.12)
    for w in partial.index:  # 절단 주차 표시
        ax.axvspan(w - 0.5, w + 0.5, color=AXIS, alpha=0.35, lw=0)
axes[-1].set_xlabel("WEEK_NO  (음영 = 7일 미만 절단 주차)")
fig.suptitle("주차별 거래 추이 — 매출·바스켓·활성가구 (장보기 거래만)",
             x=0.02, ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.97))
fig.savefig(OUT_DIR / "01a_weekly_trend.png", bbox_inches="tight")
plt.close(fig)

# ─────────────────────────────────────────────────────── B. 바스켓
say("\n" + "=" * 70)
say("B. 바스켓 단위 분포")
say("=" * 70)

bk = tx.groupby("BASKET_ID").agg(
    sales=("SALES_VALUE", "sum"),
    n_items=("PRODUCT_ID", "nunique"),
    household=("household_key", "first"),
)
qs = [0.1, 0.25, 0.5, 0.75, 0.9, 0.99]
say(f"바스켓 {len(bk):,}개")
say(f"바스켓 금액 분위: {bk.sales.quantile(qs).round(2).to_dict()}")
say(f"  평균 {bk.sales.mean():.2f} / 최대 {bk.sales.max():,.2f}")
say(f"바스켓 품목수 분위: {bk.n_items.quantile(qs).round(1).to_dict()}")
say(f"  평균 {bk.n_items.mean():.1f} / 최대 {bk.n_items.max():,}")
say(f"1품목 바스켓 비중: {(bk.n_items == 1).mean() * 100:.1f}%  "
    f"(매출 비중 {bk.loc[bk.n_items == 1, 'sales'].sum() / bk.sales.sum() * 100:.1f}%)")
say(f"가구당 방문(바스켓) 수 분위: "
    f"{bk.groupby('household').size().quantile(qs).round(0).to_dict()}")

fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
cap_s = bk.sales.quantile(0.99)
axes[0].hist(bk.sales.clip(upper=cap_s), bins=60, color=SERIES[0], edgecolor="none")
axes[0].axvline(bk.sales.median(), color=INK_2, linewidth=1.5, linestyle="--")
axes[0].annotate(f"중앙값 {bk.sales.median():.2f}",
                 (bk.sales.median(), axes[0].get_ylim()[1] * 0.88),
                 xytext=(6, 0), textcoords="offset points", color=INK_2, fontsize=9)
axes[0].set_title("바스켓당 금액 분포")
axes[0].set_xlabel(f"SALES_VALUE (상위 1% 는 {cap_s:.0f} 로 clip)")
axes[0].set_ylabel("바스켓 수")

cap_i = int(bk.n_items.quantile(0.99))
axes[1].hist(bk.n_items.clip(upper=cap_i), bins=range(1, cap_i + 2),
             color=SERIES[1], edgecolor="none")
axes[1].axvline(bk.n_items.median(), color=INK_2, linewidth=1.5, linestyle="--")
axes[1].annotate(f"중앙값 {bk.n_items.median():.0f}",
                 (bk.n_items.median(), axes[1].get_ylim()[1] * 0.88),
                 xytext=(6, 0), textcoords="offset points", color=INK_2, fontsize=9)
axes[1].set_title("바스켓당 품목 수 분포")
axes[1].set_xlabel(f"고유 상품 수 (상위 1% 는 {cap_i} 로 clip)")
for ax in axes:
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
fig.suptitle("바스켓 단위 분포 — 한 번의 장보기는 어떤 모양인가",
             x=0.02, ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.94))
fig.savefig(OUT_DIR / "01b_basket_distribution.png", bbox_inches="tight")
plt.close(fig)

# ─────────────────────────────────────────────────────── C. 파레토
say("\n" + "=" * 70)
say("C. 상품 카테고리 파레토 (장보기 거래만)")
say("=" * 70)

txp = tx.merge(products[["PRODUCT_ID", "COMMODITY_DESC"]], on="PRODUCT_ID", how="left")
com = txp.groupby("COMMODITY_DESC").SALES_VALUE.sum().sort_values(ascending=False)
com_share = com / com.sum() * 100
cum = com_share.cumsum()
for thr in (50, 80, 90):
    say(f"매출 {thr}% 도달까지 필요한 COMMODITY 수: {int((cum < thr).sum()) + 1} / {len(com)}개")
say(f"\n[상위 15 COMMODITY]")
say(pd.DataFrame({"매출": com.head(15).round(0),
                  "비중%": com_share.head(15).round(2),
                  "누적%": cum.head(15).round(1)}).to_string())

dept = tx.groupby("DEPARTMENT").SALES_VALUE.sum().sort_values(ascending=False)
say(f"\n[DEPARTMENT 상위 8 / 총 {len(dept)}개]")
say((dept.head(8) / dept.sum() * 100).round(1).to_string())

fig, axes = plt.subplots(2, 1, figsize=(9.5, 6.4))
top = com_share.head(20)[::-1]
bars = axes[0].barh(range(len(top)), top.values, color=SERIES[0], height=0.72)
axes[0].set_yticks(range(len(top)))
axes[0].set_yticklabels(top.index, fontsize=8.5, color=INK_2)
axes[0].set_title("상위 20 COMMODITY 매출 비중")
axes[0].set_xlabel("전체 매출 대비 비중 (%)")
axes[0].grid(axis="y", visible=False)
for i, v in enumerate(top.values):  # 직접 라벨
    axes[0].annotate(f"{v:.1f}%", (v, i), xytext=(4, 0), textcoords="offset points",
                     va="center", fontsize=8, color=INK_2)
axes[0].set_xlim(0, top.max() * 1.16)

axes[1].plot(range(1, len(cum) + 1), cum.values, color=SERIES[2], linewidth=2)
for thr, col in ((80, SERIES[1]), (50, MUTED)):
    n = int((cum < thr).sum()) + 1
    axes[1].axhline(thr, color=col, linewidth=1.2, linestyle="--")
    axes[1].annotate(f"{thr}% ← 상위 {n}개", (len(cum) * 0.62, thr),
                     xytext=(0, 5), textcoords="offset points", fontsize=9, color=col)
axes[1].set_title(f"누적 매출 비중 — COMMODITY {len(com)}개 전체")
axes[1].set_xlabel("매출 순위")
axes[1].set_ylabel("누적 비중 (%)")
axes[1].set_ylim(0, 101)
axes[1].set_xlim(1, len(cum))
fig.suptitle("카테고리 매출 집중도 — 어디에 장사가 몰려 있는가",
             x=0.02, ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.96))
fig.savefig(OUT_DIR / "01c_category_pareto.png", bbox_inches="tight")
plt.close(fig)

# ─────────────────────────────────────────────────────── D. 매장
say("\n" + "=" * 70)
say("D. 매장 — 매출 집중도와 가구별 주이용매장")
say("=" * 70)

st = tx.groupby("STORE_ID").SALES_VALUE.sum().sort_values(ascending=False)
st_cum = st.cumsum() / st.sum() * 100
say(f"매장 {len(st)}개 / 상위 10개 매출 비중 {st_cum.iloc[9]:.1f}% / "
    f"상위 50개 {st_cum.iloc[49]:.1f}%")
say(f"매출 80% 도달까지 필요한 매장 수: {int((st_cum < 80).sum()) + 1}개")

hh_store = tx.groupby(["household_key", "STORE_ID"]).SALES_VALUE.sum()
hh_tot = hh_store.groupby("household_key").sum()
loyal = (hh_store.groupby("household_key").max() / hh_tot * 100)
n_store = hh_store.groupby("household_key").size()
say(f"\n가구별 주이용매장 집중도(최대 매장 매출 비중) 분위: "
    f"{loyal.quantile([0.1, 0.25, 0.5, 0.75, 0.9]).round(1).to_dict()}")
say(f"  집중도 80%+ 가구: {(loyal >= 80).mean() * 100:.1f}%  /  "
    f"50% 미만 가구: {(loyal < 50).mean() * 100:.1f}%")
say(f"가구별 방문 매장 수 분위: {n_store.quantile([0.25, 0.5, 0.75, 0.9]).round(0).to_dict()}")

fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
axes[0].plot(range(1, len(st_cum) + 1), st_cum.values, color=SERIES[0], linewidth=2)
n80 = int((st_cum < 80).sum()) + 1
axes[0].axhline(80, color=SERIES[1], linewidth=1.2, linestyle="--")
axes[0].annotate(f"80% ← 상위 {n80}개 매장", (len(st_cum) * 0.35, 80),
                 xytext=(0, -14), textcoords="offset points", fontsize=9, color=SERIES[1])
axes[0].set_title(f"매장별 누적 매출 비중 — {len(st)}개 매장")
axes[0].set_xlabel("매출 순위")
axes[0].set_ylabel("누적 비중 (%)")
axes[0].set_ylim(0, 101)
axes[0].set_xlim(1, len(st_cum))

axes[1].hist(loyal, bins=40, color=SERIES[2], edgecolor="none")
axes[1].axvline(loyal.median(), color=INK_2, linewidth=1.5, linestyle="--")
axes[1].annotate(f"중앙값 {loyal.median():.0f}%", (loyal.median(), axes[1].get_ylim()[1] * 0.9),
                 xytext=(-70, 0), textcoords="offset points", color=INK_2, fontsize=9)
axes[1].set_title("가구별 주이용매장 집중도")
axes[1].set_xlabel("최다 이용 매장이 차지하는 매출 비중 (%)")
axes[1].set_ylabel("가구 수")
fig.suptitle("매장 구조 — 매출은 몇 개 매장에, 고객은 한 매장에 붙어 있는가",
             x=0.02, ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.94))
fig.savefig(OUT_DIR / "01d_store_structure.png", bbox_inches="tight")
plt.close(fig)

say("\n" + "=" * 70)
say(f"차트 4종 저장 → {OUT_DIR}")
say("=" * 70)

(OUT_DIR / "01_findings.txt").write_text(rep.getvalue(), encoding="utf-8")
sys.stdout.buffer.write(rep.getvalue().encode("utf-8"))
