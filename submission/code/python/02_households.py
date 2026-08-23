"""Phase 2 — 가구 단위 프로파일.

질문: "고객은 누구고, 얼마나 자주 오는가" → 이탈 정의(Sub goal 1)의 직접 재료
  A. RFM      가구별 Recency / Frequency / Monetary 분포
  B. 구매주기  방문 간격 분포 (가구별 '평소 주기')
  C. 이탈 정의 홀드아웃 검증 — 절대 기준 vs 상대 기준(자기 주기 배수) 비교
  D. 인구통계  801가구 vs 미상 1,699가구, 인구통계 축별 구매 패턴

실행: python 02_households.py
"""
import io
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import (ANALYSIS_WEEKS, AXIS, DATA_DIR, INK, INK_2, MUTED, OUT_DIR,
                    SERIES, load_products, load_transactions, setup_style)

setup_style()
rep = io.StringIO()


def say(*a):
    print(*a, file=rep)


LO, HI = ANALYSIS_WEEKS
products = load_products()
tx = load_transactions(exclude_non_shopping=True, analysis_window=True,
                       products=products)

say("=" * 72)
say(f"Phase 2 — 가구 단위 프로파일  (분석 구간 W{LO}~W{HI})")
say("=" * 72)
say(f"거래 {len(tx):,}행 / 가구 {tx.household_key.nunique():,} / "
    f"매출 {tx.SALES_VALUE.sum():,.0f}")

# 방문 = (가구, DAY) 단위. 같은 날 여러 바스켓은 1회 방문으로 취급.
visits = tx.groupby(["household_key", "DAY"]).SALES_VALUE.sum().reset_index()
END_DAY = tx.DAY.max()
say(f"방문(가구·일) {len(visits):,}건 / 구간 마지막 DAY {END_DAY}")

# ─────────────────────────────────────────────────────────── A. RFM
say("\n" + "=" * 72)
say("A. RFM 분포")
say("=" * 72)

rfm = visits.groupby("household_key").agg(
    last_day=("DAY", "max"),
    first_day=("DAY", "min"),
    frequency=("DAY", "count"),
    monetary=("SALES_VALUE", "sum"),
)
rfm["recency_days"] = END_DAY - rfm.last_day
rfm["tenure_days"] = rfm.last_day - rfm.first_day
rfm["avg_basket"] = rfm.monetary / rfm.frequency

qs = [0.1, 0.25, 0.5, 0.75, 0.9]
for col, label in [("recency_days", "R 최근성(마지막 방문 후 경과일)"),
                   ("frequency", "F 방문 횟수(85주간)"),
                   ("monetary", "M 총 매출"),
                   ("avg_basket", "방문당 평균 금액")]:
    q = rfm[col].quantile(qs)
    say(f"{label}: " + " / ".join(f"p{int(p*100)}={q[p]:,.1f}" for p in qs)
        + f"  (평균 {rfm[col].mean():,.1f})")

say(f"\nR 상위 꼬리: 90일+ 미방문 {(rfm.recency_days >= 90).sum():,}가구 "
    f"({(rfm.recency_days >= 90).mean()*100:.1f}%) / "
    f"180일+ {(rfm.recency_days >= 180).sum():,}가구 "
    f"({(rfm.recency_days >= 180).mean()*100:.1f}%)")
say(f"M 집중도: 상위 20% 가구가 전체 매출의 "
    f"{rfm.monetary.nlargest(int(len(rfm)*0.2)).sum()/rfm.monetary.sum()*100:.1f}%")
say(f"F 저빈도: 방문 10회 미만 {(rfm.frequency < 10).sum():,}가구 "
    f"({(rfm.frequency < 10).mean()*100:.1f}%)")

fig, axes = plt.subplots(1, 3, figsize=(11.5, 3.4))
for ax, (col, title, xlabel, color) in zip(axes, [
        ("recency_days", "R — 마지막 방문 후 경과일", "일", SERIES[0]),
        ("frequency", "F — 방문 횟수", "회 (85주간)", SERIES[1]),
        ("monetary", "M — 총 매출", "누적 SALES_VALUE", SERIES[2])]):
    cap = rfm[col].quantile(0.99)
    ax.hist(rfm[col].clip(upper=cap), bins=45, color=color, edgecolor="none")
    ax.axvline(rfm[col].median(), color=INK_2, linewidth=1.5, linestyle="--")
    ax.annotate(f"중앙값 {rfm[col].median():,.0f}",
                (rfm[col].median(), ax.get_ylim()[1] * 0.9),
                xytext=(6, 0), textcoords="offset points", color=INK_2, fontsize=9)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("가구 수")
fig.suptitle(f"가구별 RFM 분포 — {len(rfm):,}가구 (W{LO}~W{HI})",
             x=0.02, ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.93))
fig.savefig(OUT_DIR / "02a_rfm_distribution.png", bbox_inches="tight")
plt.close(fig)

# ───────────────────────────────────────────────────── B. 구매주기
say("\n" + "=" * 72)
say("B. 구매주기 (방문 간격)")
say("=" * 72)

v = visits.sort_values(["household_key", "DAY"])
v["gap"] = v.groupby("household_key").DAY.diff()
gaps = v.gap.dropna()
say(f"전체 방문 간격 {len(gaps):,}건")
say("  분위: " + " / ".join(f"p{int(p*100)}={gaps.quantile(p):.0f}일"
                          for p in [0.1, 0.25, 0.5, 0.75, 0.9, 0.99]))
say(f"  평균 {gaps.mean():.1f}일 / 최대 {gaps.max():.0f}일")

cyc = v.groupby("household_key").gap.agg(median_gap="median", n_gap="count")
cyc = cyc[cyc.n_gap >= 3]
say(f"\n가구별 '평소 주기'(방문간격 중앙값), 간격 3건 이상 {len(cyc):,}가구")
say("  분위: " + " / ".join(f"p{int(p*100)}={cyc.median_gap.quantile(p):.1f}일"
                          for p in [0.1, 0.25, 0.5, 0.75, 0.9]))
say(f"  → 가구별로 주기가 {cyc.median_gap.quantile(0.1):.0f}일 ~ "
    f"{cyc.median_gap.quantile(0.9):.0f}일까지 편차가 큼. "
    f"단일 절대 기준으로 이탈을 정의하면 주기가 긴 가구를 과잉 판정")

fig, axes = plt.subplots(1, 2, figsize=(10, 3.5))
cap = 60
axes[0].hist(gaps.clip(upper=cap), bins=cap, color=SERIES[0], edgecolor="none")
axes[0].axvline(gaps.median(), color=INK_2, linewidth=1.5, linestyle="--")
axes[0].annotate(f"중앙값 {gaps.median():.0f}일", (gaps.median(), axes[0].get_ylim()[1]*0.9),
                 xytext=(8, 0), textcoords="offset points", color=INK_2, fontsize=9)
axes[0].set_title("전체 방문 간격 분포")
axes[0].set_xlabel(f"연속 방문 사이 일수 ({cap}일 이상은 clip)")
axes[0].set_ylabel("방문 간격 수")

axes[1].hist(cyc.median_gap.clip(upper=45), bins=45, color=SERIES[1], edgecolor="none")
axes[1].axvline(cyc.median_gap.median(), color=INK_2, linewidth=1.5, linestyle="--")
axes[1].annotate(f"중앙값 {cyc.median_gap.median():.1f}일",
                 (cyc.median_gap.median(), axes[1].get_ylim()[1]*0.9),
                 xytext=(8, 0), textcoords="offset points", color=INK_2, fontsize=9)
axes[1].set_title("가구별 '평소 주기' 분포")
axes[1].set_xlabel("가구별 방문간격 중앙값 (일)")
axes[1].set_ylabel("가구 수")
fig.suptitle("구매주기 — 이탈 정의의 기준선",
             x=0.02, ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.93))
fig.savefig(OUT_DIR / "02b_purchase_cycle.png", bbox_inches="tight")
plt.close(fig)

# ─────────────────────────────────── C. 이탈 정의 홀드아웃 검증
say("\n" + "=" * 72)
say("C. 이탈 정의 검증 — 관측구간 W17~W80 / 미래구간 W81~W101 (21주)")
say("=" * 72)

OBS_END_WK = 80
obs = tx[tx.WEEK_NO <= OBS_END_WK]
fut = tx[tx.WEEK_NO > OBS_END_WK]
obs_v = obs.groupby(["household_key", "DAY"]).SALES_VALUE.sum().reset_index()
obs_end_day = obs.DAY.max()
fut_hh = set(fut.household_key.unique())

ov = obs_v.sort_values(["household_key", "DAY"])
ov["gap"] = ov.groupby("household_key").DAY.diff()
panel = ov.groupby("household_key").agg(
    last_day=("DAY", "max"), n_visit=("DAY", "count"), cycle=("gap", "median"))
panel = panel[panel.n_visit >= 4]            # 주기 추정에 간격 3건 이상 필요
panel["recency"] = obs_end_day - panel.last_day
panel["ratio"] = panel.recency / panel.cycle
panel["churned"] = ~panel.index.isin(fut_hh)

say(f"검증 대상 {len(panel):,}가구 (관측구간 방문 4회 이상) / "
    f"실제 이탈(미래 21주간 방문 0) {panel.churned.sum():,}가구 "
    f"= 기저 이탈률 {panel.churned.mean()*100:.1f}%")


def auc(score, label):
    r = pd.Series(score).rank().values
    p, n = label.sum(), (~label).sum()
    return (r[label.values].sum() - p * (p + 1) / 2) / (p * n)


say(f"\n판별력(AUC) — 절대 기준 recency: {auc(panel.recency, panel.churned):.3f}  "
    f"vs 상대 기준 recency/평소주기: {auc(panel.ratio, panel.churned):.3f}")

say("\n[절대 기준] 마지막 방문 후 경과일 구간별 이탈률")
abs_bins = [0, 7, 14, 21, 28, 42, 56, 84, 1000]
pa = panel.groupby(pd.cut(panel.recency, abs_bins, right=False)).agg(
    n=("churned", "size"), churn=("churned", "mean"))
pa["churn%"] = (pa.churn * 100).round(1)
say(pa[["n", "churn%"]].to_string())

say("\n[상대 기준] 자기 평소 주기의 몇 배나 안 왔는가")
rel_bins = [0, 0.5, 1, 1.5, 2, 3, 4, 6, 1000]
pr = panel.groupby(pd.cut(panel.ratio, rel_bins, right=False)).agg(
    n=("churned", "size"), churn=("churned", "mean"))
pr["churn%"] = (pr.churn * 100).round(1)
say(pr[["n", "churn%"]].to_string())

say("\n[이탈 정의 후보별 성능]")
cands = [("절대 28일+", panel.recency >= 28), ("절대 42일+", panel.recency >= 42),
         ("절대 56일+", panel.recency >= 56),
         ("상대 2배+", panel.ratio >= 2), ("상대 3배+", panel.ratio >= 3),
         ("상대 4배+", panel.ratio >= 4),
         ("상대 3배+ AND 절대 21일+", (panel.ratio >= 3) & (panel.recency >= 21))]
rows = []
for name, flag in cands:
    tp = (flag & panel.churned).sum()
    rows.append({"정의": name, "위험군 규모": int(flag.sum()),
                 "비중%": round(flag.mean()*100, 1),
                 "정밀도%(위험군중 실제이탈)": round(tp/max(flag.sum(), 1)*100, 1),
                 "재현율%(실제이탈중 포착)": round(tp/panel.churned.sum()*100, 1)})
say(pd.DataFrame(rows).to_string(index=False))

fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.6))
xs = [f"{int(i.left)}–{int(i.right) if i.right < 1000 else '∞'}" for i in pa.index]
axes[0].bar(range(len(pa)), pa["churn%"], color=SERIES[0], width=0.7)
axes[0].set_xticks(range(len(pa)))
axes[0].set_xticklabels(xs, fontsize=8.5)
axes[0].set_title("절대 기준 — 경과일별 실제 이탈률")
axes[0].set_xlabel("마지막 방문 후 경과일")
axes[0].set_ylabel("실제 이탈률 (%)")
for i, (val, n) in enumerate(zip(pa["churn%"], pa.n)):
    axes[0].annotate(f"{val:.0f}%  n={n}", (i, val), xytext=(0, 3),
                     textcoords="offset points", ha="center", fontsize=7.5, color=INK_2)
ymax = max(pa["churn%"].max(), pr["churn%"].max()) * 1.3  # 두 패널 공통 스케일

xs2 = [f"{i.left:g}–{i.right:g}" if i.right < 1000 else f"{i.left:g}+" for i in pr.index]
axes[1].bar(range(len(pr)), pr["churn%"], color=SERIES[1], width=0.7)
axes[1].set_xticks(range(len(pr)))
axes[1].set_xticklabels(xs2, fontsize=8.5)
axes[1].set_title("상대 기준 — 자기 주기 배수별 실제 이탈률")
axes[1].set_xlabel("경과일 ÷ 그 가구의 평소 주기 (배)")
axes[1].set_ylabel("실제 이탈률 (%)")
for i, (val, n) in enumerate(zip(pr["churn%"], pr.n)):
    axes[1].annotate(f"{val:.0f}%  n={n}", (i, val), xytext=(0, 3),
                     textcoords="offset points", ha="center", fontsize=7.5, color=INK_2)
for ax in axes:
    ax.set_ylim(0, ymax)
fig.suptitle("이탈 정의 검증 — 관측 W17~80 시점 판정 vs 이후 21주 실제 재방문",
             x=0.02, ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.93))
fig.savefig(OUT_DIR / "02c_churn_validation.png", bbox_inches="tight")
plt.close(fig)

# ───────────────────────────────────────────────── D. 인구통계
say("\n" + "=" * 72)
say("D. 인구통계 — 커버리지 편향과 축별 패턴")
say("=" * 72)

demo = pd.read_csv(DATA_DIR / "hh_demographic.csv")
rfm2 = rfm.join(cyc.median_gap).join(demo.set_index("household_key"), how="left")
rfm2["has_demo"] = rfm2.AGE_DESC.notna()

g = rfm2.groupby("has_demo").agg(
    가구수=("monetary", "size"), 매출중앙값=("monetary", "median"),
    방문중앙값=("frequency", "median"), 평소주기중앙값=("median_gap", "median"),
    방문당금액=("avg_basket", "median"))
say("[인구통계 보유 여부별 비교]")
say(g.round(1).to_string())
say(f"→ 인구통계 보유 801가구가 미상 가구보다 매출 중앙값 "
    f"{g.loc[True,'매출중앙값']/g.loc[False,'매출중앙값']:.2f}배, "
    f"방문 {g.loc[True,'방문중앙값']/g.loc[False,'방문중앙값']:.2f}배. "
    f"→ 설문 응답 가구가 더 헤비유저 (셀렉션 편향 존재, 보고서 명시 필요)")

orders = {
    "INCOME_DESC": ["Under 15K", "15-24K", "25-34K", "35-49K", "50-74K", "75-99K",
                    "100-124K", "125-149K", "150-174K", "175-199K", "200-249K", "250K+"],
    "AGE_DESC": ["19-24", "25-34", "35-44", "45-54", "55-64", "65+"],
    "HOUSEHOLD_SIZE_DESC": ["1", "2", "3", "4", "5+"],
    "HH_COMP_DESC": ["Single Male", "Single Female", "2 Adults No Kids",
                     "2 Adults Kids", "1 Adult Kids", "Unknown"],
}
d = rfm2[rfm2.has_demo]
fig, axes = plt.subplots(2, 2, figsize=(11, 6.4))
for ax, (col, order) in zip(axes.ravel(), orders.items()):
    order = [o for o in order if o in set(d[col])]
    grp = d.groupby(col).agg(med=("monetary", "median"), n=("monetary", "size")).reindex(order)
    say(f"\n[{col}] 가구당 총매출 중앙값")
    say(grp.round(0).to_string())
    ax.barh(range(len(grp)), grp["med"], color=SERIES[0], height=0.72)
    ax.set_yticks(range(len(grp)))
    ax.set_yticklabels([f"{i}  (n={int(n)})" for i, n in zip(grp.index, grp.n)], fontsize=8.5)
    ax.invert_yaxis()
    ax.set_title(col)
    ax.set_xlabel("가구당 총매출 중앙값")
    ax.grid(axis="y", visible=False)
    for i, val in enumerate(grp["med"]):
        ax.annotate(f"{val:,.0f}", (val, i), xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=8, color=INK_2)
    ax.set_xlim(0, grp["med"].max() * 1.2)
fig.suptitle("인구통계 축별 가구당 매출 — 801가구 (미상 1,699가구 제외)",
             x=0.02, ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.95))
fig.savefig(OUT_DIR / "02d_demographics.png", bbox_inches="tight")
plt.close(fig)

# 커버리지 편향 자체를 보여주는 차트 (가설 "인구통계로 이탈군을 특징지을 수 있다" 검증용)
rfm2["M분위"] = pd.qcut(rfm2.monetary, 5, labels=["최저", "하", "중", "상", "최상"])
cov = rfm2.groupby("M분위", observed=True).has_demo.agg(["size", "mean"])
cov["보유율%"] = cov["mean"] * 100
say("\n[지출 5분위별 인구통계 보유율 — 커버리지 편향]")
say(cov.rename(columns={"size": "가구수"})[["가구수", "보유율%"]].round(1).to_string())

ch = panel.join(rfm2[["has_demo"]], how="inner")
by_churn = ch.groupby("churned").has_demo.agg(["size", "mean"])
say("\n[실제 이탈 여부별 인구통계 보유율]")
say(by_churn.assign(**{"보유율%": (by_churn["mean"] * 100).round(1)})
    .rename(columns={"size": "가구수"})[["가구수", "보유율%"]].to_string())

fig, axes = plt.subplots(1, 2, figsize=(10, 3.6),
                         gridspec_kw={"width_ratios": [1.6, 1]})
axes[0].bar(range(len(cov)), cov["보유율%"], color=SERIES[0], width=0.62)
axes[0].set_xticks(range(len(cov)))
axes[0].set_xticklabels(cov.index)
axes[0].set_title("지출 5분위별 인구통계 보유율")
axes[0].set_xlabel("가구 지출 분위")
axes[0].set_ylabel("인구통계 정보 보유 비율 (%)")
for i, v in enumerate(cov["보유율%"]):
    axes[0].annotate(f"{v:.1f}%", (i, v), xytext=(0, 3), textcoords="offset points",
                     ha="center", fontsize=9, color=INK_2)
axes[0].set_ylim(0, 100)

vals = [by_churn.loc[False, "mean"] * 100, by_churn.loc[True, "mean"] * 100]
axes[1].bar(["잔존 가구", "실제 이탈 가구"], vals, color=[SERIES[0], SERIES[1]], width=0.5)
for i, v in enumerate(vals):
    axes[1].annotate(f"{v:.1f}%", (i, v), xytext=(0, 3), textcoords="offset points",
                     ha="center", fontsize=10, color=INK_2)
axes[1].set_title("이탈 여부별 인구통계 보유율")
axes[1].set_ylabel("보유 비율 (%)")
axes[1].set_ylim(0, 100)
fig.suptitle("인구통계는 헤비유저에만 붙어 있다 — 이탈 위험군에는 정보가 없다",
             x=0.02, ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.93))
fig.savefig(OUT_DIR / "02f_demographic_bias.png", bbox_inches="tight")
plt.close(fig)

# ────────────────── E. 이탈 정의 재검토 — 하드 이탈이 너무 희소하다
say("\n" + "=" * 72)
say("E. 이탈 정의 재검토 — 미래 창 길이 민감도 & '지출 급감' 대안")
say("=" * 72)

say("[미래 창 길이별 '완전 미방문' 기저율]")
win_rates = {}
for wks in (4, 8, 12, 21):
    hh = set(fut[fut.WEEK_NO <= OBS_END_WK + wks].household_key.unique())
    ch = ~panel.index.isin(hh)
    win_rates[wks] = ch.mean() * 100
    say(f"  미래 {wks:>2}주간 방문 0: {ch.sum():>4}가구 = {ch.mean()*100:5.1f}%")
say("  → 창 길이에 따라 3%~17%로 요동. '이탈'은 정의가 아니라 -선택-임을 보고서에 명시")

prior = obs[obs.WEEK_NO > OBS_END_WK - 21].groupby("household_key").SALES_VALUE.sum()
future = fut.groupby("household_key").SALES_VALUE.sum()
sp = pd.DataFrame({"prior": prior.reindex(panel.index).fillna(0),
                   "future": future.reindex(panel.index).fillna(0)})
sp = sp[sp.prior > 0]
sp["ratio"] = sp.future / sp.prior
say(f"\n[지출 급감] 직전 21주 대비 미래 21주 지출 비율 — 대상 {len(sp):,}가구")
say("  분위: " + " / ".join(f"p{int(q*100)}={sp.ratio.quantile(q):.2f}"
                          for q in (.05, .1, .25, .5, .75, .9)))
for thr in (0.3, 0.5, 0.7):
    say(f"  직전 대비 {thr*100:.0f}% 이하로 감소: {(sp.ratio <= thr).sum():>4}가구 "
        f"= {(sp.ratio <= thr).mean()*100:5.1f}%")

sp["declined"] = sp.ratio < 0.5
j = panel.join(sp[["declined", "prior"]], how="inner")
say(f"\n[예측력] 지출 50%+ 감소(기저 {j.declined.mean()*100:.1f}%)를 W{OBS_END_WK} 시점 지표로 예측")
for name, score in [("recency 경과일", j.recency), ("평소주기 cycle", j.cycle),
                    ("recency/cycle 배수", j.recency / j.cycle),
                    ("직전 21주 지출(역방향)", -j.prior)]:
    say(f"  AUC {name:<22}: {auc(score, j.declined):.3f}")

say("\n[경과일 구간별 — 하드 이탈률 vs 지출 50%+ 감소율]")
bins = [0, 7, 14, 28, 42, 84, 1000]
cut = pd.cut(j.recency, bins, right=False)
tbl = j.groupby(cut, observed=False).agg(n=("declined", "size"), decline=("declined", "mean"))
tbl["hard"] = panel.groupby(pd.cut(panel.recency, bins, right=False),
                            observed=False).churned.mean()
tbl["감소%"] = (tbl.decline * 100).round(1)
tbl["이탈%"] = (tbl.hard * 100).round(1)
say(tbl[["n", "이탈%", "감소%"]].to_string())

say("\n[직전 21주 지출 5분위별 지출 급감률]")
j["q"] = pd.qcut(j.prior, 5, labels=["최저", "하", "중", "상", "최상"])
say((j.groupby("q", observed=True).agg(n=("declined", "size"),
                                       rate=("declined", "mean"))
     .assign(**{"감소%": lambda x: (x.rate * 100).round(1)})[["n", "감소%"]]).to_string())
say("  → 저지출 가구가 더 잘 이탈. 헤비유저는 안정적 → 위험군 타겟팅 시 규모/가치 트레이드오프")

fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.6))
axes[0].bar(range(len(win_rates)), list(win_rates.values()), color=SERIES[0], width=0.6)
axes[0].set_xticks(range(len(win_rates)))
axes[0].set_xticklabels([f"{w}주" for w in win_rates])
axes[0].set_title("'이탈' 기저율은 미래 창 길이에 좌우된다")
axes[0].set_xlabel("미래 관측 창 길이")
axes[0].set_ylabel("완전 미방문 가구 비중 (%)")
for i, v in enumerate(win_rates.values()):
    axes[0].annotate(f"{v:.1f}%", (i, v), xytext=(0, 3), textcoords="offset points",
                     ha="center", fontsize=9, color=INK_2)
axes[0].set_ylim(0, max(win_rates.values()) * 1.25)

x = range(len(tbl))
axes[1].plot(x, tbl["이탈%"], color=SERIES[0], marker="o", markersize=6,
             label="완전 이탈 (21주 미방문)")
axes[1].plot(x, tbl["감소%"], color=SERIES[1], marker="s", markersize=6,
             label="지출 50%+ 감소")
axes[1].set_xticks(list(x))
axes[1].set_xticklabels([f"{int(i.left)}–{int(i.right) if i.right < 1000 else '∞'}"
                         for i in tbl.index], fontsize=8.5)
axes[1].set_title("경과일이 늘면 둘 다 오르지만, 규모는 '지출 감소'가 크다")
axes[1].set_xlabel("마지막 방문 후 경과일")
axes[1].set_ylabel("해당 구간 내 비중 (%)")
axes[1].legend(loc="upper left")
fig.suptitle("이탈 정의 재검토 — 무엇을 '이탈'로 부를지가 위험군 규모를 결정한다",
             x=0.02, ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.93))
fig.savefig(OUT_DIR / "02e_churn_definition.png", bbox_inches="tight")
plt.close(fig)

# 하위 단계에서 재사용할 가구 테이블 저장
rfm2.to_csv(OUT_DIR / "household_rfm.csv", encoding="utf-8-sig")
panel.to_csv(OUT_DIR / "churn_validation_panel.csv", encoding="utf-8-sig")
say(f"\n가구 RFM 테이블 저장 → outputs/household_rfm.csv ({len(rfm2):,}행)")

(OUT_DIR / "02_findings.txt").write_text(rep.getvalue(), encoding="utf-8")
sys.stdout.buffer.write(rep.getvalue().encode("utf-8"))
