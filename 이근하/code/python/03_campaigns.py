"""Phase 3 — 캠페인·쿠폰 프로파일.

질문: "누가 어떤 개입을 받았고, 반응했는가" → 효과검증(Sub goal 2)의 설계도
  A. 타임라인   30개 캠페인 기간 간트 + 일별 동시진행 수 → Pre-Post 가능한 '깨끗한' 캠페인 선별
  B. 타입 특성  Type A/B/C 별 규모·기간·쿠폰 수
  C. 셀렉션바이어스  타겟 가구가 원래 우량고객이었는지 (캠페인 -이전- 지출 비교)
  D. 쿠폰 퍼널  타겟 → 방문 → 대상상품 구매 → 쿠폰 사용 4단계 분해

실행: python 03_campaigns.py
"""
import io
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import (ANALYSIS_WEEKS, AXIS, DATA_DIR, INK, INK_2, MUTED, OUT_DIR,
                    SEQ, SERIES, load_products, load_transactions, setup_style)

setup_style()
rep = io.StringIO()


def say(*a):
    print(*a, file=rep)


products = load_products()
tx = load_transactions(exclude_non_shopping=True, analysis_window=True,
                       products=products)
DATA_END = tx.DAY.max()

cdesc = pd.read_csv(DATA_DIR / "campaign_desc.csv")
ctab = pd.read_csv(DATA_DIR / "campaign_table.csv")
coup = pd.read_csv(DATA_DIR / "coupon.csv")
credm = pd.read_csv(DATA_DIR / "coupon_redempt.csv")

cdesc["END_DAY_CLIP"] = cdesc.END_DAY.clip(upper=DATA_END)
cdesc["duration"] = cdesc.END_DAY_CLIP - cdesc.START_DAY + 1
TYPE_ORDER = ["TypeA", "TypeB", "TypeC"]
TYPE_COLOR = dict(zip(TYPE_ORDER, SERIES[:3]))

say("=" * 74)
say("Phase 3 — 캠페인·쿠폰 프로파일")
say("=" * 74)
say(f"거래 구간 W{ANALYSIS_WEEKS[0]}~W{ANALYSIS_WEEKS[1]} (DAY ~{DATA_END}) / "
    f"캠페인 {len(cdesc)}개 / 타겟 배정 {len(ctab):,}건")
say(f"데이터 종료일({DATA_END}) 이후까지 걸친 캠페인: "
    f"{(cdesc.END_DAY > DATA_END).sum()}개 → END_DAY를 {DATA_END}로 clip "
    f"(관측 잘린 캠페인: {list(cdesc.loc[cdesc.END_DAY > DATA_END, 'CAMPAIGN'])})")

# ─────────────────────────────────────────────── A. 타임라인 / 중첩
say("\n" + "=" * 74)
say("A. 캠페인 타임라인과 중첩")
say("=" * 74)
say(f"캠페인 기간: 최단 {cdesc.duration.min()}일 / 중앙값 {cdesc.duration.median():.0f}일 "
    f"/ 최장 {cdesc.duration.max()}일")
say(f"전체 캠페인 구간: DAY {cdesc.START_DAY.min()} ~ {cdesc.END_DAY_CLIP.max()}")

days = np.arange(cdesc.START_DAY.min(), DATA_END + 1)
active = np.array([((cdesc.START_DAY <= d) & (cdesc.END_DAY_CLIP >= d)).sum()
                   for d in days])
say(f"일별 동시진행 캠페인 수: 최소 {active.min()} / 중앙값 {np.median(active):.0f} "
    f"/ 최대 {active.max()}")
say(f"단독 진행(1개)인 날: {(active <= 1).sum()}일 / 전체 {len(days)}일 "
    f"({(active <= 1).mean()*100:.1f}%)")

# 캠페인별 중첩 수 — 적을수록 Pre-Post 해석이 깨끗함
ov = []
for _, r in cdesc.iterrows():
    others = cdesc[cdesc.CAMPAIGN != r.CAMPAIGN]
    n_ov = ((others.START_DAY <= r.END_DAY_CLIP) &
            (others.END_DAY_CLIP >= r.START_DAY)).sum()
    ov.append(n_ov)
cdesc["n_overlap"] = ov
say(f"\n중첩 캠페인 수가 적은 상위 6개 (Pre-Post 후보):")
say(cdesc.nsmallest(6, "n_overlap")[["CAMPAIGN", "DESCRIPTION", "START_DAY",
                                     "END_DAY_CLIP", "duration", "n_overlap"]]
    .to_string(index=False))
say("→ 최소 중첩이 "
    f"{cdesc.n_overlap.min()}개. 완전 단독 캠페인은 "
    f"{(cdesc.n_overlap == 0).sum()}개 → 순수 Pre-Post는 사실상 불가, "
    "대조군(비타겟) 비교가 필수")

fig, axes = plt.subplots(2, 1, figsize=(10, 7.4),
                         gridspec_kw={"height_ratios": [3, 1]}, sharex=True)
srt = cdesc.sort_values("START_DAY").reset_index(drop=True)
for i, r in srt.iterrows():
    clipped = r.END_DAY > DATA_END
    axes[0].barh(i, r.duration, left=r.START_DAY, height=0.68,
                 color=TYPE_COLOR[r.DESCRIPTION],
                 hatch="///" if clipped else None,
                 edgecolor="#fcfcfb" if clipped else "none",
                 linewidth=0.8 if clipped else 0)
axes[0].set_yticks(range(len(srt)))
axes[0].set_yticklabels([f"C{int(c)}" for c in srt.CAMPAIGN], fontsize=7.5)
axes[0].invert_yaxis()
axes[0].set_title("캠페인 기간 (사선 = 데이터 종료로 관측 잘림)")
axes[0].set_ylabel("CAMPAIGN")
axes[0].grid(axis="y", visible=False)
handles = [plt.Rectangle((0, 0), 1, 1, color=TYPE_COLOR[t]) for t in TYPE_ORDER]
axes[0].legend(handles, [f"{t} ({(cdesc.DESCRIPTION == t).sum()}개)" for t in TYPE_ORDER],
               loc="upper right")

axes[1].fill_between(days, active, color=SERIES[0], alpha=0.25, lw=0)
axes[1].plot(days, active, color=SERIES[0], linewidth=2)
axes[1].set_title("일별 동시 진행 캠페인 수")
axes[1].set_xlabel("DAY")
axes[1].set_ylabel("동시 진행 수")
axes[1].set_ylim(0, active.max() * 1.15)
fig.suptitle(f"캠페인 타임라인 — 상시 {active.min()}~{active.max()}개가 겹쳐 돌아간다 "
             f"(중앙값 {np.median(active):.0f}개, 단독 진행은 {(active <= 1).mean()*100:.0f}%뿐)",
             x=0.02, ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.965))
fig.savefig(OUT_DIR / "03a_campaign_timeline.png", bbox_inches="tight")
plt.close(fig)

# ─────────────────────────────────────────────── B. 타입별 특성
say("\n" + "=" * 74)
say("B. Type A/B/C 특성")
say("=" * 74)
n_hh = ctab.groupby("CAMPAIGN").household_key.nunique()
n_cp = coup.groupby("CAMPAIGN").COUPON_UPC.nunique()
n_pd = coup.groupby("CAMPAIGN").PRODUCT_ID.nunique()
cdesc = cdesc.assign(n_household=cdesc.CAMPAIGN.map(n_hh).fillna(0).astype(int),
                     n_coupon=cdesc.CAMPAIGN.map(n_cp).fillna(0).astype(int),
                     n_product=cdesc.CAMPAIGN.map(n_pd).fillna(0).astype(int))
tsum = cdesc.groupby("DESCRIPTION").agg(
    캠페인수=("CAMPAIGN", "size"), 기간중앙값=("duration", "median"),
    타겟가구_중앙=("n_household", "median"), 쿠폰수_중앙=("n_coupon", "median"),
    대상상품_중앙=("n_product", "median")).reindex(TYPE_ORDER)
say(tsum.round(0).to_string())
say(f"\n타겟된 가구 {ctab.household_key.nunique():,} / "
    f"거래 가구 {tx.household_key.nunique():,} → "
    f"한 번도 타겟 안 된 가구 "
    f"{tx.household_key.nunique() - ctab.household_key.nunique():,}")
per_hh = ctab.groupby("household_key").CAMPAIGN.nunique()
say(f"가구당 받은 캠페인 수: 중앙값 {per_hh.median():.0f} / 최대 {per_hh.max()} "
    f"(분위 p25={per_hh.quantile(.25):.0f} p75={per_hh.quantile(.75):.0f})")

# ─────────────────────────────────── C. 셀렉션 바이어스
say("\n" + "=" * 74)
say("C. 셀렉션 바이어스 — 타겟 가구는 원래 우량고객이었나")
say("=" * 74)

visits = tx.groupby(["household_key", "DAY"]).SALES_VALUE.sum().reset_index()
all_hh = np.array(sorted(tx.household_key.unique()))
never = np.setdiff1d(all_hh, ctab.household_key.unique())
ever = np.setdiff1d(all_hh, never)

rfm = pd.read_csv(OUT_DIR / "household_rfm.csv").set_index("household_key")
g = rfm.assign(targeted=rfm.index.isin(ever)).groupby("targeted").agg(
    가구수=("monetary", "size"), 매출중앙값=("monetary", "median"),
    방문중앙값=("frequency", "median"), 방문당금액=("avg_basket", "median"))
say("[전체 기간 기준 — 한 번이라도 타겟된 가구 vs 전혀 아닌 가구]")
say(g.round(1).to_string())
say(f"→ 타겟 가구의 매출 중앙값이 비타겟의 "
    f"{g.loc[True,'매출중앙값']/g.loc[False,'매출중앙값']:.2f}배, "
    f"방문 {g.loc[True,'방문중앙값']/g.loc[False,'방문중앙값']:.2f}배")

# 캠페인별: 시작 -이전- 56일 지출로 비교 (사후 오염 없음)
PRE = 56
rows = []
for _, r in cdesc.iterrows():
    lo, hi = r.START_DAY - PRE, r.START_DAY - 1
    if lo < visits.DAY.min():
        continue
    pre = (visits[visits.DAY.between(lo, hi)]
           .groupby("household_key").SALES_VALUE.sum()
           .reindex(all_hh).fillna(0))
    tg = ctab.loc[ctab.CAMPAIGN == r.CAMPAIGN, "household_key"].unique()
    is_t = pd.Series(np.isin(all_hh, tg), index=all_hh)
    rows.append({
        "CAMPAIGN": int(r.CAMPAIGN), "TYPE": r.DESCRIPTION,
        "타겟수": int(is_t.sum()),
        "타겟_사전지출중앙": pre[is_t].median(),
        "비타겟_사전지출중앙": pre[~is_t].median(),
        "비율": pre[is_t].median() / max(pre[~is_t].median(), 0.01),
        "타겟_사전무구매%": (pre[is_t] == 0).mean() * 100,
        "비타겟_사전무구매%": (pre[~is_t] == 0).mean() * 100,
    })
bias = pd.DataFrame(rows)
say(f"\n[캠페인별 — 시작 직전 {PRE}일 지출 비교] {len(bias)}개 캠페인")
say(bias.round(2).to_string(index=False))
say(f"\n타겟/비타겟 사전지출 비율: 중앙값 {bias["비율"].median():.2f}배 / "
    f"최소 {bias["비율"].min():.2f} / 최대 {bias["비율"].max():.2f}")
say(f"비율 1.5배 이상인 캠페인: {(bias["비율"] >= 1.5).sum()}/{len(bias)}개")
say("→ 타겟 가구는 개입 -이전-부터 이미 더 많이 쓰던 가구. "
    "단순 사후 비교는 캠페인 효과를 과대추정 → DiD 또는 성향점수 매칭 필수")

fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.8))
for t in TYPE_ORDER:
    s = bias[bias.TYPE == t]
    axes[0].scatter(s.CAMPAIGN, s.비율, color=TYPE_COLOR[t], s=55,
                    label=t, edgecolor="white", linewidth=1.2, zorder=3)
axes[0].axhline(1.0, color=INK_2, linewidth=1.4, linestyle="--")
axes[0].annotate("1.0 = 편향 없음", (bias.CAMPAIGN.max(), 1.0), xytext=(-88, 6),
                 textcoords="offset points", fontsize=9, color=INK_2)
axes[0].set_title("캠페인별 타겟/비타겟 '사전' 지출 비율")
axes[0].set_xlabel("CAMPAIGN")
axes[0].set_ylabel(f"시작 직전 {PRE}일 지출 중앙값 비율 (배)")
axes[0].legend(loc="upper left")

axes[1].scatter(bias["비타겟_사전무구매%"], bias["타겟_사전무구매%"], s=55, zorder=3,
                color=SERIES[0], edgecolor="white", linewidth=1.2)
lim = [0, max(bias["비타겟_사전무구매%"].max(), bias["타겟_사전무구매%"].max()) * 1.1]
axes[1].plot(lim, lim, color=INK_2, linewidth=1.4, linestyle="--")
axes[1].annotate("대각선 아래 = 타겟이 더 활발", (lim[1] * 0.5, lim[1] * 0.5),
                 xytext=(4, -20), textcoords="offset points", fontsize=9, color=INK_2)
axes[1].set_title("사전 기간 '무구매' 가구 비율")
axes[1].set_xlabel("비타겟 무구매 비율 (%)")
axes[1].set_ylabel("타겟 무구매 비율 (%)")
axes[1].set_xlim(lim)
axes[1].set_ylim(lim)
fig.suptitle("셀렉션 바이어스 — 타겟은 개입 전부터 이미 우량고객이었다",
             x=0.02, ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.93))
fig.savefig(OUT_DIR / "03b_selection_bias.png", bbox_inches="tight")
plt.close(fig)

# ─────────────────────────────────────────── D. 쿠폰 퍼널
say("\n" + "=" * 74)
say("D. 쿠폰 퍼널 — 타겟 → 방문 → 대상상품 구매 → 쿠폰 사용")
say("=" * 74)

cp_products = {c: set(g_.PRODUCT_ID) for c, g_ in coup.groupby("CAMPAIGN")}
redeem_pairs = set(zip(credm.household_key, credm.CAMPAIGN))
frows = []
for _, r in cdesc.iterrows():
    c = int(r.CAMPAIGN)
    tg = set(ctab.loc[ctab.CAMPAIGN == c, "household_key"].unique())
    if not tg:
        continue
    win = tx[(tx.DAY >= r.START_DAY) & (tx.DAY <= r.END_DAY_CLIP) &
             tx.household_key.isin(tg)]
    visited = set(win.household_key.unique())
    prods = cp_products.get(c, set())
    bought = set(win.loc[win.PRODUCT_ID.isin(prods), "household_key"].unique())
    redeemed = {h for h in tg if (h, c) in redeem_pairs}
    frows.append({"CAMPAIGN": c, "TYPE": r.DESCRIPTION, "①타겟": len(tg),
                  "②방문": len(visited), "③대상상품구매": len(bought),
                  "④쿠폰사용": len(redeemed)})
fn = pd.DataFrame(frows)

tot = fn[["①타겟", "②방문", "③대상상품구매", "④쿠폰사용"]].sum()
say("[전체 합계 — (가구,캠페인) 쌍 기준]")
prev = None
for k, v in tot.items():
    step = "" if prev is None else f"  단계전환율 {v/prev*100:5.1f}%"
    say(f"  {k}: {v:>7,}  (①대비 {v/tot.iloc[0]*100:5.1f}%){step}")
    prev = v

say("\n[타입별 퍼널 전환율 %]")
tt = fn.groupby("TYPE")[["①타겟", "②방문", "③대상상품구매", "④쿠폰사용"]].sum().reindex(TYPE_ORDER)
conv = pd.DataFrame({
    "타겟수": tt["①타겟"],
    "②방문/①": (tt["②방문"] / tt["①타겟"] * 100).round(1),
    "③구매/②": (tt["③대상상품구매"] / tt["②방문"] * 100).round(1),
    "④사용/③": (tt["④쿠폰사용"] / tt["③대상상품구매"] * 100).round(1),
    "최종 ④/①": (tt["④쿠폰사용"] / tt["①타겟"] * 100).round(1)})
say(conv.to_string())
say("\n→ 가장 크게 새는 구간을 보면 처방이 갈린다: "
    "②에서 새면 타겟팅, ③에서 새면 쿠폰 상품 선정, ④에서 새면 할인 매력도/인지 문제")

say("\n[캠페인별 퍼널 — 최종 사용률 상위/하위 5]")
fn["최종%"] = (fn["④쿠폰사용"] / fn["①타겟"] * 100).round(1)
say(fn.nlargest(5, "최종%").to_string(index=False))
say("...")
say(fn.nsmallest(5, "최종%").to_string(index=False))

STAGE_COLOR = [SEQ[2], SEQ[3], SEQ[4], SEQ[6]]      # ordinal ramp (step300~700)
fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.8))
labels = ["①타겟", "②방문", "③대상상품구매", "④쿠폰사용"]
axes[0].bar(range(4), tot.values, color=STAGE_COLOR, width=0.62)
axes[0].set_xticks(range(4))
axes[0].set_xticklabels(["①\n타겟", "②\n기간내 방문", "③\n대상상품 구매", "④\n쿠폰 사용"],
                        fontsize=8.5)
for i, v in enumerate(tot.values):
    axes[0].annotate(f"{v:,}\n({v/tot.iloc[0]*100:.1f}%)", (i, v), xytext=(0, 3),
                     textcoords="offset points", ha="center", fontsize=8.5, color=INK_2)
axes[0].set_title("쿠폰 퍼널 전체 — (가구,캠페인) 쌍")
axes[0].set_ylabel("쌍 수")
axes[0].set_ylim(0, tot.max() * 1.22)

w = 0.26
for i, t in enumerate(TYPE_ORDER):
    vals = [conv.loc[t, "②방문/①"], conv.loc[t, "③구매/②"], conv.loc[t, "④사용/③"]]
    axes[1].bar(np.arange(3) + (i - 1) * w, vals, width=w * 0.92,
                color=TYPE_COLOR[t], label=t)
axes[1].set_xticks(range(3))
axes[1].set_xticklabels(["②방문/①타겟", "③구매/②방문", "④사용/③구매"], fontsize=8.5)
axes[1].set_title("타입별 단계 전환율")
axes[1].set_ylabel("전환율 (%)")
axes[1].legend(loc="upper right")
fig.suptitle("쿠폰 퍼널 — 어느 단계에서 새는가",
             x=0.02, ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.93))
fig.savefig(OUT_DIR / "03c_coupon_funnel.png", bbox_inches="tight")
plt.close(fig)

bias.to_csv(OUT_DIR / "campaign_selection_bias.csv", index=False, encoding="utf-8-sig")
fn.to_csv(OUT_DIR / "campaign_funnel.csv", index=False, encoding="utf-8-sig")
cdesc.to_csv(OUT_DIR / "campaign_summary.csv", index=False, encoding="utf-8-sig")
say(f"\n테이블 저장 → campaign_selection_bias.csv / campaign_funnel.csv / campaign_summary.csv")

(OUT_DIR / "03_findings.txt").write_text(rep.getvalue(), encoding="utf-8")
sys.stdout.buffer.write(rep.getvalue().encode("utf-8"))
