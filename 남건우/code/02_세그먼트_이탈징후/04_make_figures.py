# 보고서용 차트 생성 → figures/*.png
# 데이터는 전부 dunnhumby.duckdb에서 직접 조회 (01~03 스크립트와 동일 쿼리 로직)
# 선행: 01_segments.py (hh_rfm 필요)
import logging
import duckdb
import matplotlib
import matplotlib.pyplot as plt
from pathlib import Path

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)  # 폰트 폴백 경고 억제

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "figures"
FIG.mkdir(exist_ok=True)
con = duckdb.connect(str(ROOT / "data" / "processed" / "dunnhumby.duckdb"), read_only=True)

# 팔레트 (dataviz 기본 팔레트, light mode)
SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE = "#e1e0d9", "#c3c2b7"
BLUE, RED = "#2a78d6", "#e34948"   # 다이버징: 양수/음수

matplotlib.rcParams.update({
    "font.family": ["AppleGothic", "Malgun Gothic", "NanumGothic", "sans-serif"],
    "axes.unicode_minus": False,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "text.color": INK, "axes.edgecolor": BASELINE,
    "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": INK2,
    "axes.grid": False, "font.size": 11,
})

def style_ax(ax, keep="left"):
    for side in ["top", "right", "bottom", "left"]:
        ax.spines[side].set_visible(side == keep)

# ── Fig 1. 세그먼트 프로필: 매출 기여 / 캠페인 수신률 ──────────────────
df = con.execute("""
WITH camp AS (SELECT DISTINCT household_key FROM campaign_table)
SELECT r.segment, COUNT(*) AS n_hh,
       100.0 * SUM(r.monetary) / (SELECT SUM(monetary) FROM hh_rfm) AS spend_share,
       100.0 * AVG(CASE WHEN c.household_key IS NOT NULL THEN 1 ELSE 0 END) AS recv_pct
FROM hh_rfm r LEFT JOIN camp c USING (household_key)
GROUP BY 1 ORDER BY 1
""").fetchdf()
labels = [s.replace("_", " ") for s in df["segment"]]

fig, axes = plt.subplots(1, 2, figsize=(9, 3.2), dpi=200)
for ax, col, title, unit in [(axes[0], "spend_share", "매출 기여", "%"),
                             (axes[1], "recv_pct", "캠페인 수신률", "%")]:
    y = range(len(df))[::-1]
    ax.barh(y, df[col], height=0.55, color=BLUE)
    ax.set_yticks(y, labels)
    ax.set_title(title, loc="left", fontsize=12, color=INK, pad=10)
    ax.set_xlim(0, 105)
    style_ax(ax)
    ax.xaxis.set_visible(False)
    for yi, v, n in zip(y, df[col], df["n_hh"]):
        ax.text(v + 2, yi, f"{v:.1f}{unit}", va="center", color=INK, fontsize=10)
fig.suptitle("고액 가구(S1·S2)가 매출의 84%를 내고, 캠페인도 이미 그쪽에 몰려 있다",
             x=0.01, ha="left", fontsize=13, fontweight="bold", color=INK)
fig.text(0.01, 0.895, "가구 2,500 · 세그먼트: 지출(M) × 최근성(R) 2×2 · 2년 전 기간 기준",
         fontsize=9.5, color=INK2)
fig.tight_layout(rect=[0, 0, 1, 0.82])
fig.savefig(FIG / "fig1_segments.png", bbox_inches="tight")
plt.close(fig)

# ── Fig 2. 가설 1: 사라지기 전 간격 확대 비율 ──────────────────────────
row = con.execute("""
WITH gaps AS (
    SELECT household_key,
           DAY - LAG(DAY) OVER (PARTITION BY household_key ORDER BY DAY) AS gap,
           ROW_NUMBER() OVER (PARTITION BY household_key ORDER BY DAY DESC) AS rev_rank
    FROM (SELECT DISTINCT household_key, DAY FROM transactions_base)
    QUALIFY gap IS NOT NULL),
p AS (
    SELECT t.household_key, t.n_gaps, (rfm.recency >= t.thr) AS is_inactive,
           c.recent_avg / b.baseline_med AS ratio
    FROM (SELECT household_key, COUNT(*) AS n_gaps, GREATEST(3*MEDIAN(gap),14) AS thr
          FROM gaps GROUP BY 1) t
    JOIN hh_rfm rfm USING (household_key)
    LEFT JOIN (SELECT household_key, MEDIAN(gap) AS baseline_med FROM gaps
               WHERE rev_rank > 3 GROUP BY 1) b USING (household_key)
    LEFT JOIN (SELECT household_key, AVG(gap) AS recent_avg FROM gaps
               WHERE rev_rank <= 3 GROUP BY 1) c USING (household_key))
SELECT 100.0 * AVG(CASE WHEN ratio >= 1.5 THEN 1 ELSE 0 END)
         FILTER (is_inactive) AS inact,
       COUNT(*) FILTER (is_inactive) AS n_inact,
       100.0 * AVG(CASE WHEN ratio >= 1.5 THEN 1 ELSE 0 END)
         FILTER (NOT is_inactive) AS act,
       COUNT(*) FILTER (NOT is_inactive) AS n_act
FROM p WHERE n_gaps >= 8
""").fetchone()
inact, n_inact, act, n_act = row

fig, ax = plt.subplots(figsize=(6.2, 3.4), dpi=200)
vals = [inact, act]
names = [f"말기 비활동 가구\n(n={n_inact})", f"활동 유지 가구\n(n={n_act})"]
bars = ax.bar([0, 1], vals, width=0.45, color=BLUE)
ax.set_xticks([0, 1], names)
ax.set_ylim(0, 85)
style_ax(ax, keep="bottom")
ax.yaxis.set_visible(False)
for x, v in zip([0, 1], vals):
    ax.text(x, v + 2, f"{v:.1f}%", ha="center", color=INK, fontsize=13, fontweight="bold")
ax.set_title("사라진 가구 10곳 중 7곳은 끊기기 전 구매 간격이 벌어졌다",
             loc="left", fontsize=13, fontweight="bold", color=INK, pad=24)
ax.text(0, 1.06, "마지막 3개 구매 간격이 자기 평소 중앙 간격의 1.5배 이상인 가구 비율 · "
                 "차이 +28.0%p (z=10.45, p<0.001)",
        transform=ax.transAxes, fontsize=9.5, color=INK2)
fig.tight_layout()
fig.savefig(FIG / "fig2_churn_signal.png", bbox_inches="tight")
plt.close(fig)

# ── Fig 3. 가설 2: 매칭 사전-사후 차이의 세그먼트 분해 (다이버징) ──────
# 03_campaign_effect.py의 did 로직과 동일 — 여기서는 결과 요약만 다시 계산
W, CALIPER, FLOOR = 60, 0.30, 25.0
con.execute("""
CREATE OR REPLACE TEMP VIEW hh_day AS
SELECT household_key, DAY, SUM(SALES_VALUE) AS spend FROM transactions_base GROUP BY 1, 2
""")
con.execute("""
CREATE OR REPLACE TEMP TABLE pairs AS
SELECT DISTINCT ct.household_key, ct.CAMPAIGN, cd.DESCRIPTION AS camp_type,
       cd.START_DAY AS s, cd.END_DAY AS e
FROM campaign_table ct JOIN campaign_desc cd USING (CAMPAIGN)
""")
con.execute(f"""
CREATE OR REPLACE TEMP TABLE r_spend AS
SELECT p.household_key, p.CAMPAIGN, p.camp_type,
       COALESCE(SUM(CASE WHEN d.DAY BETWEEN p.s - {W} AND p.s - 1 THEN d.spend END), 0) AS pre_spend,
       COALESCE(SUM(CASE WHEN d.DAY BETWEEN p.s AND p.s + {W} - 1 THEN d.spend END), 0) AS post_spend
FROM pairs p
LEFT JOIN hh_day d ON d.household_key = p.household_key
                  AND d.DAY BETWEEN p.s - {W} AND p.s + {W} - 1
WHERE p.s - {W} >= 1 AND p.s + {W} - 1 <= 711
  AND NOT EXISTS (SELECT 1 FROM pairs o
                  WHERE o.household_key = p.household_key AND o.CAMPAIGN != p.CAMPAIGN
                    AND o.s <= p.s + {W} - 1 AND o.e >= p.s - {W})
GROUP BY 1, 2, 3
""")
con.execute(f"""
CREATE OR REPLACE TEMP TABLE pool AS
SELECT c.CAMPAIGN, nr.household_key,
       COALESCE(SUM(CASE WHEN d.DAY BETWEEN c.s - {W} AND c.s - 1 THEN d.spend END), 0) AS pre_spend,
       COALESCE(SUM(CASE WHEN d.DAY BETWEEN c.s AND c.s + {W} - 1 THEN d.spend END), 0) AS post_spend
FROM (SELECT DISTINCT CAMPAIGN, s FROM pairs WHERE s - {W} >= 1 AND s + {W} - 1 <= 711) c
JOIN (SELECT household_key, NULL AS first_recv FROM hh_rfm
      WHERE household_key NOT IN (SELECT DISTINCT household_key FROM campaign_table)
      UNION ALL SELECT household_key, MIN(s) FROM pairs GROUP BY 1) nr
  ON nr.first_recv IS NULL OR nr.first_recv > c.s + {W} - 1
LEFT JOIN hh_day d ON d.household_key = nr.household_key
                  AND d.DAY BETWEEN c.s - {W} AND c.s + {W} - 1
GROUP BY 1, 2
""")
did = con.execute(f"""
SELECT r.camp_type, rfm.segment, COUNT(*) AS n,
       AVG((r.post_spend - r.pre_spend) * 7.0 / {W}
           - (SELECT AVG((k.post_spend - k.pre_spend) * 7.0 / {W}) FROM pool k
              WHERE k.CAMPAIGN = r.CAMPAIGN
                AND ABS(k.pre_spend - r.pre_spend) <= GREATEST({CALIPER} * r.pre_spend, {FLOOR})))
       AS did_wk
FROM r_spend r JOIN hh_rfm rfm USING (household_key)
WHERE r.camp_type IN ('TypeA', 'TypeB')
GROUP BY 1, 2 ORDER BY 1, 2
""").fetchdf()

fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.4), dpi=200, sharex=True)
for ax, ctype in zip(axes, ["TypeA", "TypeB"]):
    sub = did[did["camp_type"] == ctype].sort_values("segment")
    y = range(len(sub))[::-1]
    colors = [BLUE if v >= 0 else RED for v in sub["did_wk"]]
    ax.barh(y, sub["did_wk"], height=0.55, color=colors)
    ax.axvline(0, color=BASELINE, lw=1)
    ax.set_yticks(y, [f"{s.replace('_', ' ')}\n(n={n})" for s, n in zip(sub["segment"], sub["n"])],
                  fontsize=9.5)
    ax.set_title(f"{ctype}", loc="left", fontsize=12, color=INK, pad=8)
    ax.set_xlim(-9, 15)
    style_ax(ax, keep="left")
    ax.spines["left"].set_visible(False)
    ax.tick_params(left=False)
    ax.xaxis.set_visible(False)
    for yi, v in zip(y, sub["did_wk"]):
        ax.text(v + (0.4 if v >= 0 else -0.4), yi, f"{v:+.1f}$/주",
                va="center", ha="left" if v >= 0 else "right", color=INK, fontsize=10)
fig.suptitle("같은 캠페인이라도 고액 가구에서만 증분이 확인된다 (매칭 사전-사후 차이)",
             x=0.01, ha="left", fontsize=13, fontweight="bold", color=INK)
fig.text(0.01, 0.9, "주간 지출 변화량 − 매칭 비교군 변화량 ($/주) · 깨끗한 60일 창 · "
                    "TypeC는 표본 부족(n=16)으로 제외 · '차이'이지 '효과' 아님",
         fontsize=9.5, color=INK2)
fig.tight_layout(rect=[0, 0, 1, 0.8])
fig.savefig(FIG / "fig3_did_by_segment.png", bbox_inches="tight")
plt.close(fig)

con.close()
print("figures saved:", *[p.name for p in sorted(FIG.glob("*.png"))])
