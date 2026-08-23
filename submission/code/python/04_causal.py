"""Phase 4 — causal_data(진열/전단) 처리 전략과 프로파일.

causal_data는 36,786,524행. 통째로 pandas 로드 금지 → 청크 2패스 구조.
  PASS 1  전체 스캔하며 집계만 (값 분포 / 주차·매장 커버리지 / 상품별 노출 변동)
  PASS 2  후보 카테고리 상품만 필터해 압축 저장 → 이후 분석은 이 작은 테이블만 사용

질문:
  A. 커버리지  어느 매장·주차·상품까지 정보가 있는가 (없는 곳은 '노출 없음'이 아니라 '정보 없음')
  B. 노출 구조  display / mailer 값 분포와 주차별 노출률
  C. 대상 모집단  주이용매장이 causal 커버 매장인 가구 (Phase 1 발견 활용)
  D. 후보 선정   노출 변동이 있고 판매량도 있는 카테고리
  E. 실현성 검증 후보 카테고리에서 진열/전단과 판매량의 1차 관계가 실제로 보이는가

실행: python 04_causal.py   (2패스 · 수 분 소요)
"""
import io
import sys
import time

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import (ANALYSIS_WEEKS, AXIS, DATA_DIR, INK, INK_2, MUTED, OUT_DIR,
                    SEQ, SERIES, load_products, load_transactions, setup_style)

setup_style()
rep = io.StringIO()
t0 = time.time()


def say(*a):
    print(*a, file=rep)


CHUNK = 4_000_000
DTYPE = {"PRODUCT_ID": np.int32, "STORE_ID": np.int32,
         "WEEK_NO": np.int16, "display": "str", "mailer": "str"}

products = load_products()
tx = load_transactions(exclude_non_shopping=True, analysis_window=True,
                       products=products)
LO, HI = ANALYSIS_WEEKS

say("=" * 76)
say("Phase 4 — causal_data 처리 전략과 프로파일")
say("=" * 76)

# ══════════════════════════════════════════════════ PASS 1 — 집계 전용
say("\n[PASS 1] 36,786,524행 청크 스캔 — 집계만 수집")
disp_vc, mail_vc = {}, {}
week_stat = {}                      # week -> [rows, promo_rows]
store_rows = {}                     # store -> rows
prod_cells = {}                     # product -> [cells, display_cells, mailer_cells]
n_rows = 0
for ch in pd.read_csv(DATA_DIR / "causal_data.csv", chunksize=CHUNK, dtype=DTYPE):
    n_rows += len(ch)
    d_on = ch.display.ne("0").values
    m_on = ch.mailer.ne("0").values
    for v, c in ch.display.value_counts().items():
        disp_vc[v] = disp_vc.get(v, 0) + int(c)
    for v, c in ch.mailer.value_counts().items():
        mail_vc[v] = mail_vc.get(v, 0) + int(c)

    gw = pd.DataFrame({"w": ch.WEEK_NO.values, "promo": (d_on | m_on)}) \
        .groupby("w").promo.agg(["size", "sum"])
    for w, (sz, pm) in gw.iterrows():
        cur = week_stat.setdefault(int(w), [0, 0])
        cur[0] += int(sz); cur[1] += int(pm)

    for s, c in ch.STORE_ID.value_counts().items():
        store_rows[s] = store_rows.get(s, 0) + int(c)

    gp = pd.DataFrame({"p": ch.PRODUCT_ID.values, "d": d_on, "m": m_on}) \
        .groupby("p").agg(cells=("d", "size"), dis=("d", "sum"), mai=("m", "sum"))
    for p, (cells, dis, mai) in gp.iterrows():
        cur = prod_cells.setdefault(int(p), [0, 0, 0])
        cur[0] += int(cells); cur[1] += int(dis); cur[2] += int(mai)
say(f"  완료 {n_rows:,}행 / {time.time()-t0:.0f}초")

# ─────────────────────────────────────────────── A. 커버리지
say("\n" + "=" * 76)
say("A. 커버리지 — 어디까지 정보가 있는가")
say("=" * 76)
ws = pd.DataFrame(week_stat, index=["rows", "promo_rows"]).T.sort_index()
ws["promo%"] = (ws.promo_rows / ws.rows * 100).round(1)
causal_stores = set(store_rows)
causal_products = set(prod_cells)
say(f"주차 범위 {ws.index.min()}~{ws.index.max()} ({len(ws)}주) / "
    f"매장 {len(causal_stores)} / 상품 {len(causal_products):,}")
say(f"거래 데이터 대비: 매장 {len(causal_stores)}/{tx.STORE_ID.nunique()} "
    f"({len(causal_stores)/tx.STORE_ID.nunique()*100:.1f}%) / "
    f"상품 {len(causal_products):,}/{tx.PRODUCT_ID.nunique():,} "
    f"({len(causal_products)/tx.PRODUCT_ID.nunique()*100:.1f}%)")
say(f"분석구간(W{LO}~W{HI}) 중 causal 없는 주차: "
    f"{sorted(set(range(LO, HI+1)) - set(ws.index))}")

in_cs = tx.STORE_ID.isin(causal_stores)
say(f"\n거래 커버리지 — causal 매장에서 발생한 거래: {in_cs.sum():,}행 "
    f"({in_cs.mean()*100:.1f}%) / 매출 비중 "
    f"{tx.loc[in_cs,'SALES_VALUE'].sum()/tx.SALES_VALUE.sum()*100:.1f}%")
say("→ 매장 수로는 21%지만 매출로는 그보다 크다. causal 매장이 대형 매장 위주")

# ─────────────────────────────────────────── B. 노출 구조
say("\n" + "=" * 76)
say("B. display / mailer 값 분포")
say("=" * 76)
ds = pd.Series(disp_vc).sort_values(ascending=False)
ms = pd.Series(mail_vc).sort_values(ascending=False)
say("[display] 0=진열 없음, 1~9/A=매대 위치 코드")
say((ds / ds.sum() * 100).round(2).to_string())
say(f"  → 진열 있음(≠0): {(1 - ds.get('0', 0)/ds.sum())*100:.1f}%")
say("\n[mailer] 0=미게재, A~X=전단 내 위치 코드")
say((ms / ms.sum() * 100).round(2).to_string())
say(f"  → 전단 게재(≠0): {(1 - ms.get('0', 0)/ms.sum())*100:.1f}%")
say(f"\n주차별 프로모션 셀 비율: 중앙값 {ws['promo%'].median():.1f}% / "
    f"최소 {ws['promo%'].min():.1f}%(W{ws['promo%'].idxmin()}) / "
    f"최대 {ws['promo%'].max():.1f}%(W{ws['promo%'].idxmax()})")

fig, axes = plt.subplots(1, 3, figsize=(12.5, 3.5))
axes[0].bar(range(len(ds)), (ds / ds.sum() * 100).values, color=SERIES[0], width=0.7)
axes[0].set_xticks(range(len(ds)))
axes[0].set_xticklabels(ds.index, fontsize=8.5)
axes[0].set_title("display 값 분포 (0 = 진열 없음)")
axes[0].set_xlabel("display 코드")
axes[0].set_ylabel("셀 비중 (%)")
axes[1].bar(range(len(ms)), (ms / ms.sum() * 100).values, color=SERIES[1], width=0.7)
axes[1].set_xticks(range(len(ms)))
axes[1].set_xticklabels(ms.index, fontsize=8.5)
axes[1].set_title("mailer 값 분포 (0 = 미게재)")
axes[1].set_xlabel("mailer 코드")
axes[1].set_ylabel("셀 비중 (%)")
axes[2].plot(ws.index, ws["promo%"], color=SERIES[2], linewidth=2)
axes[2].axvspan(LO, HI, color=AXIS, alpha=0.18, lw=0)
axes[2].annotate(f"분석구간 W{LO}~W{HI}", (LO, ws['promo%'].max()),
                 xytext=(4, -12), textcoords="offset points", fontsize=9, color=INK_2)
axes[2].set_title("주차별 프로모션 노출 셀 비율")
axes[2].set_xlabel("WEEK_NO")
axes[2].set_ylabel("display 또는 mailer ≠ 0 (%)")
axes[2].set_ylim(0, ws["promo%"].max() * 1.15)
fig.suptitle("causal_data 노출 구조 — 진열·전단은 어떻게 기록되어 있는가",
             x=0.02, ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.93))
fig.savefig(OUT_DIR / "04a_causal_structure.png", bbox_inches="tight")
plt.close(fig)

# ─────────────────────────────────── C. 대상 모집단 (Phase 1 발견 활용)
say("\n" + "=" * 76)
say("C. 분석 대상 모집단 — 주이용매장이 causal 커버 매장인 가구")
say("=" * 76)
hh_store = tx.groupby(["household_key", "STORE_ID"]).SALES_VALUE.sum()
primary = hh_store.groupby("household_key").idxmax().apply(lambda t: t[1])
share = (hh_store.groupby("household_key").max() /
         hh_store.groupby("household_key").sum() * 100)
pop = primary[primary.isin(causal_stores)].index
say(f"전체 가구 {tx.household_key.nunique():,} → 주이용매장이 causal 매장인 가구 "
    f"{len(pop):,} ({len(pop)/tx.household_key.nunique()*100:.1f}%)")
say(f"  이 가구들의 주이용매장 집중도 중앙값: {share[pop].median():.1f}%")
say(f"  이 가구들이 전체 매출에서 차지하는 비중: "
    f"{tx.loc[tx.household_key.isin(pop),'SALES_VALUE'].sum()/tx.SALES_VALUE.sum()*100:.1f}%")
strict = share[pop][share[pop] >= 70].index
say(f"  집중도 70% 이상까지 좁히면: {len(strict):,}가구 "
    f"(노출-반응 인과 해석이 가장 깨끗한 집단)")

# ───────────────────────────────────────── D. 후보 카테고리 선정
say("\n" + "=" * 76)
say("D. 후보 카테고리 — 노출 '변동'이 있고 판매량도 있는 것")
say("=" * 76)
pc = pd.DataFrame(prod_cells, index=["cells", "dis", "mai"]).T
pc.index.name = "PRODUCT_ID"
pc["disp_rate"] = pc.dis / pc.cells
pc["mail_rate"] = pc.mai / pc.cells

txc = tx[in_cs]                                    # causal 매장 거래만
psale = txc.groupby("PRODUCT_ID").agg(sales=("SALES_VALUE", "sum"),
                                      units=("QUANTITY", "sum"))
pj = pc.join(psale, how="inner").join(
    products.set_index("PRODUCT_ID")[["COMMODITY_DESC", "DEPARTMENT"]])
say(f"causal × 거래 양쪽에 존재하는 상품: {len(pj):,}개 "
    f"(causal 매장 매출의 {pj.sales.sum()/txc.SALES_VALUE.sum()*100:.1f}%)")

com = pj.groupby("COMMODITY_DESC").agg(
    상품수=("sales", "size"), 매출=("sales", "sum"),
    진열률=("disp_rate", "mean"), 전단률=("mail_rate", "mean")).sort_values(
    "매출", ascending=False)
com["진열률"] = (com.진열률 * 100).round(1)
com["전단률"] = (com.전단률 * 100).round(1)
# 변동 조건: 진열률 5~60% (항상 진열/전혀 진열 없음은 비교 불가)
cand = com[(com.진열률.between(5, 60)) & (com.매출 > com.매출.quantile(0.7))].head(12)
say(f"\n[후보 카테고리 12개] 조건: 진열률 5~60%(변동 존재) & 매출 상위 30%")
say(cand.round(0).to_string())
say("→ 진열률이 0%에 가깝거나 60%를 넘는 카테고리는 대조(노출 없음) 셀이 부족해 제외")

# ══════════════════════════════════════ PASS 2 — 후보만 압축 저장
cand_products = set(pj[pj.COMMODITY_DESC.isin(cand.index)].index)
say(f"\n[PASS 2] 후보 카테고리 상품 {len(cand_products):,}개만 필터해 재스캔")
keep = []
for ch in pd.read_csv(DATA_DIR / "causal_data.csv", chunksize=CHUNK, dtype=DTYPE):
    sub = ch[ch.PRODUCT_ID.isin(cand_products) & ch.STORE_ID.isin(causal_stores)]
    if len(sub):
        keep.append(sub)
promo = pd.concat(keep, ignore_index=True)
promo["display_on"] = promo.display.ne("0")
promo["mailer_on"] = promo.mailer.ne("0")
say(f"  압축 결과 {len(promo):,}행 (원본의 {len(promo)/n_rows*100:.1f}%) / "
    f"{time.time()-t0:.0f}초 경과")
try:
    promo.to_parquet(OUT_DIR / "promo_candidates.parquet", index=False)
    saved = "promo_candidates.parquet"
except Exception:
    promo.to_csv(OUT_DIR / "promo_candidates.csv.gz", index=False, compression="gzip")
    saved = "promo_candidates.csv.gz"
say(f"  저장 → outputs/{saved}  (이후 분석은 이 파일만 읽으면 됨)")

# ────────────────────────────── E. 실현성 검증 — 1차 관계가 보이는가
say("\n" + "=" * 76)
say("E. 실현성 검증 — 진열/전단과 판매량의 1차 관계")
say("=" * 76)
say("주의: causal_data에 셀이 -존재하는- (상품,매장,주차)만 사용 (inner join).")
say("      셀이 없는 조합은 '노출 없음'이 아니라 '정보 없음'이므로 0으로 채우지 않음.")

txw = (txc[txc.PRODUCT_ID.isin(cand_products)]
       .groupby(["PRODUCT_ID", "STORE_ID", "WEEK_NO"])
       .agg(units=("QUANTITY", "sum"), sales=("SALES_VALUE", "sum")).reset_index())
cells = promo[["PRODUCT_ID", "STORE_ID", "WEEK_NO", "display_on", "mailer_on"]]
m = cells.merge(txw, on=["PRODUCT_ID", "STORE_ID", "WEEK_NO"], how="left")
m[["units", "sales"]] = m[["units", "sales"]].fillna(0)
say(f"\n분석 셀 {len(m):,}개 (판매 발생 셀 {(m.units > 0).mean()*100:.1f}%)")

lift_rows = []
for name, col in [("진열(display)", "display_on"), ("전단(mailer)", "mailer_on")]:
    on, off = m[m[col]], m[~m[col]]
    lift_rows.append({
        "개입": name, "노출 셀": len(on), "미노출 셀": len(off),
        "노출_평균판매수량": on.units.mean(), "미노출_평균판매수량": off.units.mean(),
        "수량 리프트": on.units.mean() / max(off.units.mean(), 1e-9),
        "노출_판매발생%": (on.units > 0).mean() * 100,
        "미노출_판매발생%": (off.units > 0).mean() * 100})
lift = pd.DataFrame(lift_rows)
say("\n[전체 후보 상품 기준 1차 리프트]")
say(lift.round(2).to_string(index=False))

say("\n[카테고리별 진열 리프트]")
mc = m.merge(products.set_index("PRODUCT_ID")[["COMMODITY_DESC"]],
             left_on="PRODUCT_ID", right_index=True)
rows = []
for c, g_ in mc.groupby("COMMODITY_DESC"):
    on, off = g_[g_.display_on], g_[~g_.display_on]
    if len(on) < 100 or len(off) < 100:
        continue
    rows.append({"COMMODITY": c, "노출셀": len(on), "미노출셀": len(off),
                 "노출평균": on.units.mean(), "미노출평균": off.units.mean(),
                 "리프트": on.units.mean() / max(off.units.mean(), 1e-9)})
cl = pd.DataFrame(rows).sort_values("리프트", ascending=False)
say(cl.round(2).to_string(index=False))
say(f"\n→ 진열 리프트 중앙값 {cl.리프트.median():.2f}배. "
    f"모든 후보 카테고리에서 1배 초과: {(cl.리프트 > 1).all()}")
say("→ 단, 이는 상관관계. 진열 선정 자체가 '잘 팔릴 상품'에 몰릴 수 있으므로 "
    "Sub goal 3 본분석에서는 상품 고정효과(within-product) 또는 주차 통제 필요")

fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
x = np.arange(len(cl))
w = 0.38
axes[0].barh(x - w/2, cl.미노출평균, height=w*0.92, color=SERIES[0], label="미노출")
axes[0].barh(x + w/2, cl.노출평균, height=w*0.92, color=SERIES[1], label="진열 노출")
axes[0].set_yticks(x)
axes[0].set_yticklabels(cl.COMMODITY, fontsize=8)
axes[0].invert_yaxis()
axes[0].set_title("카테고리별 주간 평균 판매수량 — 진열 유무")
axes[0].set_xlabel("셀당 평균 판매 수량")
axes[0].grid(axis="y", visible=False)
axes[0].legend(loc="lower right")

axes[1].barh(x, cl.리프트, height=0.7, color=SERIES[2])
axes[1].axvline(1.0, color=INK_2, linewidth=1.4, linestyle="--")
axes[1].set_yticks(x)
axes[1].set_yticklabels([""] * len(cl))
axes[1].invert_yaxis()
axes[1].set_title("진열 리프트 (노출 ÷ 미노출)")
axes[1].set_xlabel("배")
axes[1].grid(axis="y", visible=False)
for i, v in enumerate(cl.리프트):
    axes[1].annotate(f"{v:.2f}×", (v, i), xytext=(4, 0), textcoords="offset points",
                     va="center", fontsize=8.5, color=INK_2)
axes[1].set_xlim(0, cl.리프트.max() * 1.2)
fig.suptitle("실현성 검증 — 진열된 주에 실제로 더 팔렸다 (상관관계, 인과 아님)",
             x=0.02, ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.94))
fig.savefig(OUT_DIR / "04b_promo_lift.png", bbox_inches="tight")
plt.close(fig)

# ───────── F. 이상 징후 추적 — 코드별 강도 & 무게상품 문제
say("\n" + "=" * 76)
say("F. 이상 징후 추적")
say("=" * 76)

say("[F-1] mailer 이진화(게재/미게재)는 잘못된 처리다 — 코드별로 강도가 다름")
mm = promo[["PRODUCT_ID", "STORE_ID", "WEEK_NO", "mailer", "display"]].merge(
    txw, on=["PRODUCT_ID", "STORE_ID", "WEEK_NO"], how="left")
mm[["units", "sales"]] = mm[["units", "sales"]].fillna(0)
base_u = mm.loc[mm.mailer == "0", "units"].mean()
base_s = mm.loc[mm.mailer == "0", "sales"].mean()
mrows = []
for code, g_ in mm.groupby("mailer"):
    if len(g_) < 1000:
        continue
    mrows.append({"mailer": code, "셀 수": len(g_),
                  "평균수량": g_.units.mean(), "수량리프트": g_.units.mean() / base_u,
                  "평균매출": g_.sales.mean(), "매출리프트": g_.sales.mean() / base_s})
mt = pd.DataFrame(mrows).sort_values("매출리프트", ascending=False)
say(mt.round(3).to_string(index=False))
say("  참조 코드 의미: 0=미게재, A=내부면, C=내부면 라인, D=1면(front page), "
    "F=뒷면, H=랩 앞면, J/P=쿠폰, L=랩 뒷면, X/Z=무료")
say(f"  → A(내부면)가 전체 게재의 대부분인데 리프트가 낮아 이진 평균을 끌어내림. "
    f"최고 코드 리프트 {mt.매출리프트.max():.2f}배 vs 최저 {mt.매출리프트.min():.2f}배")

say("\n[F-2] display 코드별 강도 (매대 위치)")
base_du = mm.loc[mm.display == "0", "units"].mean()
base_ds = mm.loc[mm.display == "0", "sales"].mean()
drows = []
for code, g_ in mm.groupby("display"):
    if len(g_) < 1000:
        continue
    drows.append({"display": code, "셀 수": len(g_),
                  "평균수량": g_.units.mean(), "수량리프트": g_.units.mean() / base_du,
                  "평균매출": g_.sales.mean(), "매출리프트": g_.sales.mean() / base_ds})
dt = pd.DataFrame(drows).sort_values("매출리프트", ascending=False)
say(dt.round(3).to_string(index=False))
say("  참조: 0=없음, 1=매장 전면, 2=매장 후면, 3=전면 엔드캡, 4=중앙통로 엔드캡, "
    "5=후면 엔드캡, 6=측면 엔드캡, 7=통로 내, 9=보조 진열, A=선반 내")

say("\n[F-3] 리프트가 1 미만인 카테고리 — QUANTITY(무게상품) 문제인지 확인")
odd = cl[cl.리프트 < 1].COMMODITY.tolist()
say(f"  대상: {odd}")
for c in odd:
    g_ = mc[mc.COMMODITY_DESC == c]
    on, off = g_[g_.display_on], g_[~g_.display_on]
    say(f"  {c}: 수량리프트 {on.units.mean()/max(off.units.mean(),1e-9):.2f}배 / "
        f"매출리프트 {on.sales.mean()/max(off.sales.mean(),1e-9):.2f}배 "
        f"| 진열된 상품 {on.PRODUCT_ID.nunique()}종 vs 미진열 {off.PRODUCT_ID.nunique()}종 "
        f"| 진열 셀 비중 {len(on)/len(g_)*100:.1f}%")
say("  → 수량·매출 리프트가 -같은 방향-이므로 무게단위(정책 #3) 문제는 아님.")
say("  → 원인은 상품 구성(composition): 이 카테고리는 진열이 드물고(셀 3~11%), "
    "진열된 것이 저회전 소수 SKU에 몰려 있어 그룹 간 상품이 애초에 다름.")
say("  → 교훈: 카테고리 단위 단순 평균 비교는 위험. 반드시 -같은 상품 내- "
    "진열 주 vs 비진열 주 비교(상품 고정효과)로 설계해야 함.")

say("\n[F-4] 분석 단위 재검토 — (상품,매장,주차) 셀은 너무 희소하다")
say(f"  분석 셀 {len(m):,}개 중 판매 발생 {(m.units>0).mean()*100:.1f}%만. "
    f"셀당 평균 수량 {m.units.mean():.3f}")
agg_pw = (m.groupby(["PRODUCT_ID", "WEEK_NO"])
          .agg(units=("units", "sum"), sales=("sales", "sum"),
               disp=("display_on", "max")).reset_index())
say(f"  (상품,주차)로 올리면 {len(agg_pw):,}셀 / 판매 발생 "
    f"{(agg_pw.units>0).mean()*100:.1f}% / 셀당 평균 수량 {agg_pw.units.mean():.2f}")
say("  → 2,500가구 패널이 115개 매장에 흩어져 매장 단위는 관측이 거의 0. "
    "Sub goal 3 본분석 단위는 (상품,주차) 또는 (카테고리,주차) 권장")

fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
for ax, t, order_col, title, xlabel in [
        (axes[0], mt, "mailer", "전단 위치(mailer) 코드별 매출 리프트", "mailer 코드"),
        (axes[1], dt, "display", "진열 위치(display) 코드별 매출 리프트", "display 코드")]:
    t2 = t[t[order_col] != "0"]
    ax.bar(range(len(t2)), t2.매출리프트, color=SERIES[0], width=0.7)
    ax.axhline(1.0, color=INK_2, linewidth=1.4, linestyle="--")
    ax.set_xticks(range(len(t2)))
    ax.set_xticklabels(t2[order_col], fontsize=9)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("미노출(0) 대비 매출 리프트 (배)")
    for i, v in enumerate(t2.매출리프트):
        ax.annotate(f"{v:.1f}", (i, v), xytext=(0, 3), textcoords="offset points",
                    ha="center", fontsize=8, color=INK_2)
    ax.set_ylim(0, t2.매출리프트.max() * 1.2)
fig.suptitle("노출 '위치'가 효과를 가른다 — 이진 플래그로 뭉개면 효과가 사라진다",
             x=0.02, ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.93))
fig.savefig(OUT_DIR / "04c_promo_code_lift.png", bbox_inches="tight")
plt.close(fig)
mt.to_csv(OUT_DIR / "mailer_code_lift.csv", index=False, encoding="utf-8-sig")
dt.to_csv(OUT_DIR / "display_code_lift.csv", index=False, encoding="utf-8-sig")

com.to_csv(OUT_DIR / "causal_commodity_profile.csv", encoding="utf-8-sig")
cl.to_csv(OUT_DIR / "promo_lift_firstlook.csv", index=False, encoding="utf-8-sig")
pd.Series(sorted(pop)).to_csv(OUT_DIR / "causal_population_households.csv",
                              index=False, header=["household_key"])
say(f"\n테이블 저장 → causal_commodity_profile.csv / promo_lift_firstlook.csv / "
    f"causal_population_households.csv")
say(f"총 소요 {time.time()-t0:.0f}초")

(OUT_DIR / "04_findings.txt").write_text(rep.getvalue(), encoding="utf-8")
sys.stdout.buffer.write(rep.getvalue().encode("utf-8"))
