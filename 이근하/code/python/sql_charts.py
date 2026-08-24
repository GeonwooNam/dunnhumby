"""Sub goal 1 (SQL 분석) 결과를 발표용 그래프로 — 숫자는 subgoal1_이탈분석_SQL.md 기준."""
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
from pathlib import Path

for f in ("Malgun Gothic", "AppleGothic", "NanumGothic"):
    if any(x.name == f for x in fm.fontManager.ttflist):
        plt.rcParams["font.family"] = f
        break
plt.rcParams.update({
    "axes.unicode_minus": False, "figure.facecolor": "#fcfcfb",
    "axes.facecolor": "#fcfcfb", "savefig.facecolor": "#fcfcfb",
    "axes.edgecolor": "#c3c2b7", "axes.grid": True, "axes.axisbelow": True,
    "grid.color": "#e1e0d9", "axes.spines.top": False, "axes.spines.right": False,
    "xtick.color": "#898781", "ytick.color": "#898781", "figure.dpi": 130})
BLUE, ORANGE, AQUA, INK, INK2 = "#2a78d6", "#eb6834", "#1baf7a", "#0b0b0b", "#52514e"
OUT = Path("outputs"); OUT.mkdir(exist_ok=True)

# ── 1. 경과일별 이탈률 (STEP 2) — 35일 급증
labels = ["~20", "21~27", "28~34", "35~41", "42~48", "49+"]
rate = [1.1, 0.9, 1.2, 5.7, 11.9, 16.2]
colors = [BLUE if r < 3 else ORANGE for r in rate]
fig, ax = plt.subplots(figsize=(8, 4))
ax.bar(range(len(rate)), rate, color=colors, width=0.68)
ax.axvline(2.5, color=INK2, ls="--", lw=1.3)
ax.annotate("35일: 이탈률 5배 급증\n(1.2% → 5.7%)", (2.5, 14),
            xytext=(10, 0), textcoords="offset points", fontsize=10,
            color=INK, fontweight="bold")
for i, r in enumerate(rate):
    ax.annotate(f"{r}%", (i, r), xytext=(0, 3), textcoords="offset points",
                ha="center", fontsize=9, color=INK2)
ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels)
ax.set_xlabel("마지막 방문 후 경과일"); ax.set_ylabel("실제 이탈률 (%)")
ax.set_title("이탈 정의의 근거 — 34일까지 평평하다 35일에서 급증",
             loc="left", fontsize=13, fontweight="bold", color=INK)
ax.set_ylim(0, 19)
fig.tight_layout(); fig.savefig(OUT / "sql_1_churn_by_recency.png", bbox_inches="tight")
plt.close(fig)

# ── 2. 타겟 깔때기 (STEP 4)
stages = ["전체 가구", "이탈 위험군\n(35일+)", "고가치\n(상위 20%)", "★ 이탈초기\n(35~69일)"]
vals = [2492, 426, 85, 50]
ramp = ["#9ec5f4", "#5598e7", "#256abf", "#eb6834"]
pct = [100, 17.1, 3.4, 2.0]
fig, ax = plt.subplots(figsize=(8.5, 4.2))
for i, (v, c, pc) in enumerate(zip(vals, ramp, pct)):
    left = (vals[0] - v) / 2
    ax.barh(i, v, left=left, color=c, height=0.62)
    # 라벨: 큰 막대는 안쪽, 작은 막대는 오른쪽 바깥
    if v > 400:
        ax.annotate(f"{v:,}가구  ({pc:g}%)", (vals[0]/2, i), ha="center", va="center",
                    fontsize=11, fontweight="bold", color="white" if i > 0 else INK)
    else:
        ax.annotate(f"{v:,}가구  ({pc:g}%)", (left + v + 40, i), ha="left", va="center",
                    fontsize=11, fontweight="bold", color=c)
ax.set_yticks(range(len(stages))); ax.set_yticklabels(stages, fontsize=10)
ax.invert_yaxis(); ax.set_xticks([]); ax.set_xlim(0, vals[0] * 1.05); ax.grid(False)
ax.spines["left"].set_visible(False); ax.spines["bottom"].set_visible(False)
ax.set_title("2,492가구 → 50가구, 4겹의 이유로 좁혀진 최종 타겟",
             loc="left", fontsize=13, fontweight="bold", color=INK)
fig.tight_layout(); fig.savefig(OUT / "sql_2_funnel.png", bbox_inches="tight")
plt.close(fig)

# ── 3. 수신율 격차 (STEP 6) — 씀씀이 vs 쿠폰 수신
fig, axes = plt.subplots(1, 2, figsize=(9.5, 4))
g = ["위험군\n우량고객", "정상군\n우량고객"]
axes[0].bar(g, [45.4, 50.9], color=[ORANGE, BLUE], width=0.5)
for i, v in enumerate([45.4, 50.9]):
    axes[0].annotate(f"{v}", (i, v), xytext=(0, 3), textcoords="offset points",
                     ha="center", fontsize=11, color=INK2, fontweight="bold")
axes[0].set_title("방문당 지출 (씀씀이) — 거의 같다", loc="left",
                  fontsize=11.5, fontweight="bold", color=INK)
axes[0].set_ylim(0, 60); axes[0].set_ylabel("방문당 지출")
axes[1].bar(g, [41.8, 81.8], color=[ORANGE, BLUE], width=0.5)
for i, v in enumerate([41.8, 81.8]):
    axes[1].annotate(f"{v}%", (i, v), xytext=(0, 3), textcoords="offset points",
                     ha="center", fontsize=11, color=INK2, fontweight="bold")
axes[1].set_title("캠페인 수신율 — 절반뿐", loc="left",
                  fontsize=11.5, fontweight="bold", color=INK)
axes[1].set_ylim(0, 95); axes[1].set_ylabel("수신율 (%)")
fig.suptitle("씀씀이는 비슷한데 쿠폰은 절반만 — 우량 단골이 타겟팅에서 배제된다",
             x=0.02, ha="left", fontsize=13, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.94))
fig.savefig(OUT / "sql_3_reach_gap.png", bbox_inches="tight"); plt.close(fig)

# ── 4. 위험군 가치 (STEP 3) — 가구 vs 매출 비중
fig, ax = plt.subplots(figsize=(7.5, 3.6))
x = np.arange(2); w = 0.35
ax.bar(x - w/2, [17.1, 82.9], w, label="가구 비중", color=BLUE)
ax.bar(x + w/2, [5.9, 94.1], w, label="매출 비중", color=AQUA)
for i, (a, b) in enumerate(zip([17.1, 82.9], [5.9, 94.1])):
    ax.annotate(f"{a}%", (i - w/2, a), xytext=(0, 3), textcoords="offset points",
                ha="center", fontsize=9, color=INK2)
    ax.annotate(f"{b}%", (i + w/2, b), xytext=(0, 3), textcoords="offset points",
                ha="center", fontsize=9, color=INK2)
ax.set_xticks(x); ax.set_xticklabels(["위험군", "정상군"])
ax.set_ylabel("비중 (%)"); ax.legend(frameon=False)
ax.set_title("위험군은 가구 17%지만 매출은 6% — 대부분 저가치",
             loc="left", fontsize=12.5, fontweight="bold", color=INK)
ax.set_ylim(0, 105)
fig.tight_layout(); fig.savefig(OUT / "sql_4_risk_value.png", bbox_inches="tight")
plt.close(fig)

print("saved 4 charts to outputs/")
