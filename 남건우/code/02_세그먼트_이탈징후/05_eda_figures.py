# EDA 문서용 차트 생성 → figures/eda_*.png
# 1) 주차별 활동 가구 (램프인 = 좌측 절단 증거)
# 2) 캠페인 타임라인 (전부 DAY 224 이후 시작 + 겹침 구조)
# 3) 인구통계 보유 가구의 지출 편향
import logging
import duckdb
import matplotlib
import matplotlib.pyplot as plt
from pathlib import Path

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "figures"
FIG.mkdir(exist_ok=True)
con = duckdb.connect(str(ROOT / "data" / "processed" / "dunnhumby.duckdb"), read_only=True)

SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE = "#e1e0d9", "#c3c2b7"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"  # 카테고리 슬롯 1~3

matplotlib.rcParams.update({
    "font.family": ["AppleGothic", "Malgun Gothic", "NanumGothic", "sans-serif"],
    "axes.unicode_minus": False,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "text.color": INK, "axes.edgecolor": BASELINE,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "font.size": 11,
})

def style_ax(ax):
    for side in ["top", "right"]:
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", color=GRID, lw=0.7)
    ax.set_axisbelow(True)

# ── EDA Fig 1. 주차별 활동 가구 수 (램프인) ────────────────────────────
df = con.execute("""
SELECT WEEK_NO, COUNT(DISTINCT household_key) AS n_hh
FROM transactions_base GROUP BY 1 ORDER BY 1
""").fetchdf()

fig, ax = plt.subplots(figsize=(8, 3.2), dpi=200)
ax.plot(df["WEEK_NO"], df["n_hh"], color=BLUE, lw=2)
ax.axvspan(1, 10, color=GRID, alpha=0.5, zorder=0)
ax.text(5.5, 1350, "~10주차\n램프인 구간", ha="center", fontsize=9, color=INK2)
ax.set_xlim(1, 102)
ax.set_ylim(0, 1500)
ax.set_xlabel("주차 (WEEK_NO)")
style_ax(ax)
ax.set_title("주차별 활동 가구 수 — 패널이 서서히 차오른다 (좌측 절단)",
             loc="left", fontsize=13, fontweight="bold", color=INK, pad=22)
ax.text(0, 1.05, "관측 초기의 '첫 구매'는 신규 가입이 아니라 패널 편입일 가능성 — 초기 ~10주는 리텐션 분석에서 별도 취급",
        transform=ax.transAxes, fontsize=9.5, color=INK2)
fig.tight_layout()
fig.savefig(FIG / "eda1_weekly_households.png", bbox_inches="tight")
plt.close(fig)

# ── EDA Fig 2. 캠페인 타임라인 ────────────────────────────────────────
camp = con.execute("""
SELECT CAMPAIGN, DESCRIPTION AS camp_type, START_DAY, END_DAY
FROM campaign_desc ORDER BY START_DAY, CAMPAIGN
""").fetchdf()
cmap = {"TypeA": BLUE, "TypeB": ORANGE, "TypeC": AQUA}

fig, ax = plt.subplots(figsize=(8, 4.2), dpi=200)
for i, r in camp.iterrows():
    ax.plot([r["START_DAY"], r["END_DAY"]], [i, i], lw=3.5,
            color=cmap[r["camp_type"]], solid_capstyle="butt")
ax.axvline(224, color=MUTED, lw=1, ls="--")
ax.text(214, 15, "첫 캠페인 시작 DAY 224\n→ 모든 캠페인에\n사전 기간 확보", ha="right",
        va="center", fontsize=9, color=INK2)
ax.set_xlim(1, 711)
ax.set_ylim(-1, 30)
ax.invert_yaxis()
ax.set_yticks([])
ax.set_xlabel("DAY (1~711, 상대 시간)")
for side in ["top", "right", "left"]:
    ax.spines[side].set_visible(False)
ax.grid(axis="x", color=GRID, lw=0.7)
ax.set_axisbelow(True)
handles = [plt.Line2D([], [], color=c, lw=3.5) for c in cmap.values()]
ax.legend(handles, [f"{t} ({n}개)" for t, n in
                    camp["camp_type"].value_counts().sort_index().items()],
          loc="upper left", bbox_to_anchor=(0.02, 0.98), frameon=False, fontsize=9.5)
ax.set_title("캠페인 30개 타임라인 — 활성 기간이 서로 촘촘히 겹친다",
             loc="left", fontsize=13, fontweight="bold", color=INK, pad=22)
ax.text(0, 1.03, "행 = 캠페인 1개(시작~종료), 시작일 순 정렬 · 같은 가구가 여러 캠페인을 겹쳐 받는 구조 → 전후 비교 시 '깨끗한 창' 필터 필요",
        transform=ax.transAxes, fontsize=9.5, color=INK2)
fig.tight_layout()
fig.savefig(FIG / "eda2_campaign_timeline.png", bbox_inches="tight")
plt.close(fig)

# ── EDA Fig 3. 인구통계 보유 가구의 지출 편향 ─────────────────────────
df = con.execute("""
WITH demo AS (SELECT DISTINCT household_key FROM hh_demographic)
SELECT CASE WHEN d.household_key IS NOT NULL THEN '인구통계 있음' ELSE '인구통계 없음' END AS grp,
       COUNT(*) AS n_hh, AVG(m.spend) AS avg_spend
FROM (SELECT household_key, SUM(SALES_VALUE) AS spend FROM transactions_base GROUP BY 1) m
LEFT JOIN demo d USING (household_key)
GROUP BY 1 ORDER BY 1 DESC
""").fetchdf()

fig, ax = plt.subplots(figsize=(6.2, 3.2), dpi=200)
y = range(len(df))[::-1]
ax.barh(y, df["avg_spend"], height=0.5, color=BLUE)
ax.set_yticks(y, [f"{g}\n(n={n:,})" for g, n in zip(df["grp"], df["n_hh"])], fontsize=10)
for side in ["top", "right", "bottom"]:
    ax.spines[side].set_visible(False)
ax.xaxis.set_visible(False)
for yi, v in zip(y, df["avg_spend"]):
    ax.text(v + 100, yi, f"${v:,.0f}", va="center", color=INK, fontsize=11)
ax.set_xlim(0, 7000)
ax.set_title("인구통계 있는 801가구(32%)는 평균 지출이 2.6배 높은 우량 편향 표본",
             loc="left", fontsize=12.5, fontweight="bold", color=INK, pad=20)
ax.text(0, 1.04, "가구당 2년 상품 매출(net_spend) 평균 · 소득/연령 세그먼트 분석은 '전체'가 아니라 이 부분집합 분석임을 병기",
        transform=ax.transAxes, fontsize=9, color=INK2)
fig.tight_layout()
fig.savefig(FIG / "eda3_demo_bias.png", bbox_inches="tight")
plt.close(fig)

con.close()
print("figures saved:", *[p.name for p in sorted(FIG.glob("eda*.png"))])
