"""Phase 5 — 종합: 이탈 위험군과 마케팅 개입의 교차 검증.

Sub goal 1(이탈)과 2(마케팅)를 연결하는 질문:
  "이탈 위험군은 캠페인을 받고 있는가?"

Phase 2: 위험군은 저지출·저빈도 가구.  Phase 3: 캠페인 타겟은 사전지출 3.5배 우량고객.
→ 두 발견이 맞다면 위험군은 캠페인에서 구조적으로 배제되고 있어야 한다. 이를 직접 검증.

실행: python 05_synthesis.py
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


AT_RISK_DAYS = 42          # Phase 2에서 확정한 1차 위험군 기준
products = load_products()
tx = load_transactions(exclude_non_shopping=True, analysis_window=True,
                       products=products)
cdesc = pd.read_csv(DATA_DIR / "campaign_desc.csv")
ctab = pd.read_csv(DATA_DIR / "campaign_table.csv")
DATA_END = tx.DAY.max()
cdesc = cdesc[cdesc.START_DAY <= DATA_END]

visits = tx.groupby(["household_key", "DAY"]).SALES_VALUE.sum().reset_index()
all_hh = np.array(sorted(tx.household_key.unique()))

say("=" * 76)
say("Phase 5 — 종합: 이탈 위험군 × 마케팅 개입 교차 검증")
say("=" * 76)
say(f"위험군 기준: 마지막 방문 후 {AT_RISK_DAYS}일 이상 경과 (Phase 2 확정)")
say(f"캠페인 {len(cdesc)}개 / 가구 {len(all_hh):,}")

rows = []
for _, r in cdesc.iterrows():
    s = r.START_DAY
    prior = visits[visits.DAY < s]
    if prior.empty:
        continue
    last = prior.groupby("household_key").DAY.max().reindex(all_hh)
    active = last.notna()                              # 그 시점에 이력이 있는 가구만
    recency = (s - last)[active]
    at_risk = recency >= AT_RISK_DAYS
    tg = set(ctab.loc[ctab.CAMPAIGN == r.CAMPAIGN, "household_key"])
    targeted = pd.Series(recency.index.isin(tg), index=recency.index)
    rows.append({
        "CAMPAIGN": int(r.CAMPAIGN), "TYPE": r.DESCRIPTION, "START_DAY": int(s),
        "위험군수": int(at_risk.sum()), "정상군수": int((~at_risk).sum()),
        "위험군_타겟률": targeted[at_risk].mean() * 100,
        "정상군_타겟률": targeted[~at_risk].mean() * 100,
    })
X = pd.DataFrame(rows)
X["격차배수"] = X.정상군_타겟률 / X.위험군_타겟률.replace(0, np.nan)

say("\n[캠페인별 — 시작 시점 위험군 vs 정상군의 타겟팅률]")
say(X.round(2).to_string(index=False))
say(f"\n요약: 위험군 타겟률 중앙값 {X.위험군_타겟률.median():.1f}% vs "
    f"정상군 {X.정상군_타겟률.median():.1f}%  "
    f"→ 정상군이 {X.정상군_타겟률.median()/max(X.위험군_타겟률.median(),1e-9):.1f}배 더 많이 타겟됨")
say(f"정상군 타겟률이 더 높은 캠페인: {(X.정상군_타겟률 > X.위험군_타겟률).sum()}/{len(X)}개")

# 위험군이 들고 있는 매출 규모 (놓치는 가치)
rfm = pd.read_csv(OUT_DIR / "household_rfm.csv").set_index("household_key")
risk_now = rfm[rfm.recency_days >= AT_RISK_DAYS]
say(f"\n[구간 종료 시점 위험군의 가치]")
say(f"  위험군 {len(risk_now):,}가구 ({len(risk_now)/len(rfm)*100:.1f}%) / "
    f"이들의 누적 매출 {risk_now.monetary.sum():,.0f} "
    f"(전체의 {risk_now.monetary.sum()/rfm.monetary.sum()*100:.1f}%)")
say(f"  위험군 중 한 번도 타겟 안 된 가구: "
    f"{(~risk_now.index.isin(ctab.household_key.unique())).sum():,}가구 "
    f"({(~risk_now.index.isin(ctab.household_key.unique())).mean()*100:.1f}%)")
normal = rfm[rfm.recency_days < AT_RISK_DAYS]
say(f"  비교: 정상군 중 한 번도 타겟 안 된 가구 "
    f"{(~normal.index.isin(ctab.household_key.unique())).mean()*100:.1f}%")

# 위험군 내부 가치 세분화 — "위험군 전체"는 가치가 작다는 반론에 답하기
say("\n" + "=" * 76)
say("위험군 내부 세분화 — 구하러 갈 가치가 있는 가구는 누구인가")
say("=" * 76)
rfm["M분위"] = pd.qcut(rfm.monetary, 5, labels=["최저", "하", "중", "상", "최상"])
rfm["위험"] = rfm.recency_days >= AT_RISK_DAYS
rfm["타겟이력"] = rfm.index.isin(ctab.household_key.unique())
seg = rfm[rfm.위험].groupby("M분위", observed=True).agg(
    가구수=("monetary", "size"), 누적매출=("monetary", "sum"),
    타겟이력률=("타겟이력", "mean"))
seg["매출비중%"] = (seg.누적매출 / rfm.monetary.sum() * 100)
seg["타겟이력률%"] = seg.타겟이력률 * 100
say("[위험군 385가구를 과거 지출 분위로 쪼개면]")
say(seg[["가구수", "누적매출", "매출비중%", "타겟이력률%"]]
    .style.format({"누적매출": "{:,.0f}", "매출비중%": "{:.2f}",
                   "타겟이력률%": "{:.1f}"}).to_string()
    if hasattr(seg, "style") else seg.to_string())

hv = rfm[rfm.위험 & rfm.M분위.isin(["상", "최상"])]
say(f"\n[검증] 위험군 ∩ 과거 지출 상위 40% = {len(hv)}가구 "
    f"(위험군의 {len(hv)/len(rfm[rfm.위험])*100:.1f}%)")
say(f"  이들의 캠페인 이력 보유율: {hv.타겟이력.mean()*100:.1f}% "
    f"(이력 없는 가구 {(~hv.타겟이력).sum()}곳뿐)")
say("\n→ ⚠️ '방치된 고가치 위험군'이라는 가설은 데이터가 지지하지 않는다.")
say("   위험군 385가구 중 353가구(92%)가 지출 하위 60%이고, "
    "고가치 위험군 33가구는 이미 88~96%가 캠페인을 받았다.")
say("   즉 27배 타겟팅 격차는 '방치'가 아니라 -가치 기준 선별-의 결과. "
    "리테일러의 타겟팅은 단기 ROI 관점에서 대체로 합리적이다.")
say("   → Sub goal 1의 실행 방안은 '위험군 재타겟팅'이 될 수 없다. 다른 각도가 필요.")

# 대안 세그먼트: 지출 급감 그룹 (Phase 2 E에서 14.7%로 확인된 그룹)
say("\n" + "=" * 76)
say("대안 세그먼트 — 지출 급감 그룹에는 고가치 가구가 있는가")
say("=" * 76)
OBS = 80
obs, fut = tx[tx.WEEK_NO <= OBS], tx[tx.WEEK_NO > OBS]
prior = obs[obs.WEEK_NO > OBS - 21].groupby("household_key").SALES_VALUE.sum()
future = fut.groupby("household_key").SALES_VALUE.sum()
sp = pd.DataFrame({"prior": prior, "future": future.reindex(prior.index).fillna(0)})
sp = sp[sp.prior > 0]
sp["ratio"] = sp.future / sp.prior
sp["급감"] = sp.ratio < 0.5
sp["P분위"] = pd.qcut(sp.prior, 5, labels=["최저", "하", "중", "상", "최상"])
sp["타겟이력"] = sp.index.isin(ctab.household_key.unique())

d = sp[sp.급감]
dseg = d.groupby("P분위", observed=True).agg(
    가구수=("prior", "size"), 직전지출합=("prior", "sum"),
    타겟이력률=("타겟이력", "mean"))
dseg["급감률%"] = (d.groupby("P분위", observed=True).size() /
                sp.groupby("P분위", observed=True).size() * 100)
dseg["타겟이력률%"] = dseg.타겟이력률 * 100
say(f"지출 50%+ 급감 가구 {len(d):,}곳 ({len(d)/len(sp)*100:.1f}%) — 직전 지출 분위별")
say(dseg[["가구수", "직전지출합", "급감률%", "타겟이력률%"]].to_string())
hd = d[d.P분위.isin(["상", "최상"])]
say(f"\n→ 급감 ∩ 직전 지출 상위 40% = **{len(hd)}가구**")
say(f"   이들이 급감 직전 21주에 쓴 금액 {hd.prior.sum():,.0f} "
    f"(급감 그룹 전체 {d.prior.sum():,.0f}의 {hd.prior.sum()/d.prior.sum()*100:.0f}%)")
say(f"   위험군∩고가치 33가구와 비교해 {len(hd)/max(len(hv),1):.1f}배 규모")
say("→ 완전 이탈보다 -지출 급감- 이 실행 가능한 타겟이다: 규모가 크고 고가치 가구가 실제로 포함됨.")

fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
o = X.sort_values("START_DAY")
axes[0].plot(range(len(o)), o.정상군_타겟률, color=SERIES[0], marker="o",
             markersize=5, label="정상군 (최근 방문 있음)")
axes[0].plot(range(len(o)), o.위험군_타겟률, color=SERIES[1], marker="s",
             markersize=5, label=f"이탈 위험군 ({AT_RISK_DAYS}일+ 미방문)")
axes[0].set_xticks(range(0, len(o), 3))
axes[0].set_xticklabels([f"C{c}" for c in o.CAMPAIGN[::3]], fontsize=8)
axes[0].set_title("캠페인별 타겟팅률 — 위험군이 일관되게 낮다")
axes[0].set_xlabel("캠페인 (시작일 순)")
axes[0].set_ylabel("해당 집단 중 타겟된 비율 (%)")
axes[0].legend(loc="upper left")

ax = axes[1]
x = np.arange(len(seg))
ax.bar(x, seg.가구수, color=SERIES[0], width=0.6, label="위험군 가구 수")
ax.set_xticks(x)
ax.set_xticklabels(seg.index, fontsize=9)
ax.set_xlabel("과거 지출 분위")
ax.set_ylabel("위험군 가구 수")
ax.set_title("위험군은 대부분 저가치이고, 고가치는 이미 커버됨")
for i, (n, t) in enumerate(zip(seg.가구수, seg["타겟이력률%"])):
    ax.annotate(f"{int(n)}가구\n캠페인이력 {t:.0f}%", (i, n), xytext=(0, 3),
                textcoords="offset points", ha="center", fontsize=8, color=INK_2)
ax.set_ylim(0, seg.가구수.max() * 1.35)
fig.suptitle("타겟팅 격차는 27배지만 '방치'는 아니다 — 위험군의 92%가 저가치",
             x=0.02, ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.93))
fig.savefig(OUT_DIR / "05a_risk_vs_targeting.png", bbox_inches="tight")
plt.close(fig)

X.to_csv(OUT_DIR / "risk_targeting_gap.csv", index=False, encoding="utf-8-sig")
say("\n테이블 저장 → risk_targeting_gap.csv")
(OUT_DIR / "05_findings.txt").write_text(rep.getvalue(), encoding="utf-8")
sys.stdout.buffer.write(rep.getvalue().encode("utf-8"))
