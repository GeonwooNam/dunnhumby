# -*- coding: utf-8 -*-
"""results.md §11 시각화 5종 생성 (Tableau 초안 대체용 PNG)"""
import pandas as pd, numpy as np, matplotlib.pyplot as plt
import koreanize_matplotlib  # noqa
import matplotlib.ticker as mtick

UP = "/mnt/user-data/uploads/"
OUT = "/mnt/user-data/outputs/viz/"
import os; os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({"figure.dpi": 150, "axes.spines.top": False, "axes.spines.right": False})
BLUE, GREEN, GRAY, RED, ORANGE = "#3b6ea5", "#4c9a6a", "#9aa0a6", "#c0504d", "#e8a33d"

# ── 1. 타겟 퍼널 ─────────────────────────────────────────
f = pd.read_csv(UP + "viz_funnel.csv")
fig, ax = plt.subplots(figsize=(8, 3.6))
y = np.arange(len(f))[::-1]
colors = [GRAY, GRAY, BLUE, BLUE, RED]
bars = ax.barh(y, f.n, color=colors, height=0.62)
for yi, (n, s) in zip(y, zip(f.n, f.stage)):
    ax.text(n + 30, yi, f"{n:,}", va="center", fontsize=10, fontweight="bold")
ax.set_yticks(y); ax.set_yticklabels(f.stage, fontsize=9.5)
ax.set_xlim(0, 2800); ax.set_xlabel("가구 수")
ax.set_title("타겟 퍼널 — 고가치 완전 이탈은 2년에 3가구", fontsize=12, fontweight="bold", loc="left")
plt.tight_layout(); plt.savefig(OUT + "viz3_funnel.png"); plt.close()

# ── 2. 임계별 PR: 윈도우 vs 스냅샷 ──────────────────────
pr = pd.read_csv(UP + "step3_precision_recall.csv")
sn = pd.read_csv(UP + "supp_snapshot_d558.csv")
fig, axes = plt.subplots(1, 2, figsize=(10.5, 4), sharey=False)
for ax, grp in zip(axes, ["전체", "고가치"]):
    w = pr[pr.group == grp]
    s = sn[(sn.group == grp) & sn.rule.str.startswith("개인화")].copy()
    s["thr"] = s.rule.str.extract(r"x([\d.]+)").astype(float)
    base = sn[(sn.group == grp) & (sn.rule == "35일 일괄")].iloc[0]
    ax.plot(w.threshold, w.precision * 100, "o--", color=GRAY, label="윈도우 채점 (한 번이라도 경보)")
    ax.plot(s.thr, s.precision * 100, "o-", color=BLUE, label="스냅샷 채점 (경보 지속 중)")
    ax.axhline(base.precision * 100, color=RED, lw=1.2, ls=":", label=f"35일 일괄 스냅샷 ({base.precision*100:.1f}%)")
    n_churn = int(w.iloc[0].churned); n_all = int(w.iloc[0].n)
    ax.axhline(n_churn / n_all * 100, color="k", lw=0.8, ls="-", alpha=0.35)
    ax.text(3.02, n_churn / n_all * 100, f"base rate {n_churn/n_all*100:.1f}%", fontsize=8, va="bottom", alpha=0.6)
    ax.set_title(f"{grp} (n={n_all:,}, 이탈 {n_churn})", fontsize=11)
    ax.set_xlabel("경보 임계 (×중앙간격)"); ax.set_ylabel("precision (%)")
    ax.set_xticks([1.5, 2.0, 2.5, 3.0])
axes[0].legend(fontsize=8.5, frameon=False)
fig.suptitle("경보 '발생'은 무정보, '지속'이 정보 — 채점 프레임별 precision", fontsize=12.5, fontweight="bold")
plt.tight_layout(); plt.savefig(OUT + "viz1_precision_frames.png"); plt.close()

# ── 3. 리드타임 분포 ─────────────────────────────────────
lt = pd.read_csv(UP + "step4_leadtime.csv")
order = ["~4일(고빈도)", "5~7일", "8~14일", "15일+(저빈도)"]
cmap = dict(zip(order, [BLUE, "#5f8fc4", "#8fb3d9", RED]))
fig, ax = plt.subplots(figsize=(8.5, 4))
bins = np.arange(-20, 41, 4)
bottom = np.zeros(len(bins) - 1)
for g in order:
    cnt, _ = np.histogram(lt[lt.gap_group == g].lead_days, bins=bins)
    ax.bar(bins[:-1] + 2, cnt, width=3.6, bottom=bottom, color=cmap[g], label=f"{g} (n={ (lt.gap_group==g).sum() })")
    bottom += cnt
ax.axvline(0, color="k", lw=1)
med = lt.lead_days.median()
ax.axvline(med, color=GREEN, lw=1.5, ls="--")
ax.text(med + 0.5, ax.get_ylim()[1] * 0.92, f"중앙 +{med:.1f}일", color=GREEN, fontsize=10, fontweight="bold")
ax.text(-19, ax.get_ylim()[1] * 0.92, "← 35일 일괄이 빠름", fontsize=9, alpha=0.7)
ax.set_xlabel("리드타임 (일) — 양수 = 개인화 규칙이 35일 일괄보다 빠름")
ax.set_ylabel("이탈 가구 수")
ax.set_title("개인화 규칙의 리드타임 (이탈자 36가구) — 저빈도만 역전", fontsize=12, fontweight="bold", loc="left")
ax.legend(fontsize=8.5, frameon=False)
plt.tight_layout(); plt.savefig(OUT + "viz2_leadtime.png"); plt.close()

# ── 4. 대표 가구 타임라인 ────────────────────────────────
tl = pd.read_csv(UP + "viz_timeline_examples.csv")
al = pd.read_csv(UP + "step2_alerts_thr2.csv").set_index("household_key")
hhs = tl.household_key.unique()
fig, axes = plt.subplots(len(hhs), 1, figsize=(10, 4.6), sharex=True)
for ax, hh in zip(axes, hhs):
    d = tl[tl.household_key == hh]
    v = d[d.type == "visit"].day
    ax.vlines(v, 0, 1, color=GRAY, lw=0.9, alpha=0.75)
    for t, c, lab, ls in [("alert", BLUE, "경보(×2)", "-"), ("day35_rule", RED, "35일 도달", "--")]:
        for x in d[d.type == t].day:
            ax.axvline(x, color=c, lw=1.8, ls=ls)
    for x in d[d.type == "campaign_start"].day:
        ax.plot(x, 1.18, "v", color=ORANGE, ms=6, clip_on=False)
    churned = bool(al.loc[hh].churned) if hh in al.index else False
    tag = "이탈(정탐)" if churned else "복귀(오탐)"
    ax.set_ylabel(f"HH {hh}\n{tag}", rotation=0, ha="right", va="center", fontsize=9)
    ax.set_yticks([]); ax.set_ylim(0, 1.3)
    ax.axvspan(559, 705, color=GREEN, alpha=0.06)
axes[0].set_title("대표 가구 타임라인 — 회색: 방문, 파랑: 경보, 빨강 점선: 35일 도달, ▼ 캠페인 수신, 초록 음영: 홀드아웃",
                  fontsize=10.5, fontweight="bold", loc="left")
axes[-1].set_xlabel("DAY (111 = W17)")
plt.tight_layout(); plt.savefig(OUT + "viz4_timelines.png"); plt.close()

# ── 5. 경보 후 노출 비교 ─────────────────────────────────
ex = pd.read_csv(UP + "step5_exposure_summary.csv")
fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.8), sharey=True)
metrics = [("캠페인수신", "캠페인 수신율"), ("쿠폰사용", "쿠폰 사용률")]
for ax, (col, title) in zip(axes, metrics):
    x = np.arange(2)
    for i, grp in enumerate(["전체 경보", "고가치 경보"]):
        sub = ex[ex["대상"] == grp].set_index("구분")
        vals = [sub.loc["복귀", col] * 100, sub.loc["이탈", col] * 100]
        ns = [int(sub.loc["복귀", "n"]), int(sub.loc["이탈", "n"])]
        b = ax.bar(x + i * 0.38, vals, width=0.34, color=[GREEN, RED][i] if False else [BLUE, ORANGE][i],
                   label=grp)
        for xi, v, n in zip(x + i * 0.38, vals, ns):
            ax.text(xi, v + 1.2, f"{v:.1f}%\n(n={n})", ha="center", fontsize=8)
    ax.set_xticks(x + 0.19); ax.set_xticklabels(["복귀", "이탈"])
    ax.set_title(title, fontsize=11); ax.set_ylim(0, 80)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter())
axes[0].legend(fontsize=8.5, frameon=False)
fig.suptitle("경보 기간 중 개입 노출 — 어느 셀도 체계적으로 닿지 않음 (기술적 관찰, 이탈 셀 소표본)",
             fontsize=11.5, fontweight="bold")
plt.tight_layout(); plt.savefig(OUT + "viz5_exposure.png"); plt.close()
print("done:", os.listdir(OUT))
