"""H2-4 검증 — 쿠폰은 증분 매출을 만드는가?

설계: 캠페인별 DiD(이중차분) + 사전지출 5분위 층화 매칭
  - 셀렉션 바이어스(타겟이 사전에 3.52배 더 씀)를 층화로 제거
  - 세 수준에서 동시 측정해 카니발라이제이션을 판별:
      (a) 쿠폰 대상 상품 지출  → 그 상품이 더 팔렸나
      (b) 해당 카테고리 전체    → 카테고리 파이가 커졌나
      (c) 가구 전체 지출        → 진짜 증분인가
  - DiD는 반드시 '캠페인 안에서' 계산한 뒤 캠페인 간 집계 (층화가 캠페인별이므로)
  - 플라시보 테스트: 캠페인 없던 가짜 기간에 같은 계산 → 0이 나와야 설계가 건강

실행: python 06_incremental.py
"""
import io
import sys

import numpy as np
import pandas as pd

from common import DATA_DIR, load_products, load_transactions

out = io.StringIO()


def p(*a):
    print(*a, file=out)


pr = load_products()
tx = load_transactions(True, analysis_window=True, products=pr)
tx = tx.merge(pr[["PRODUCT_ID", "COMMODITY_DESC"]], on="PRODUCT_ID", how="left")
cdesc = pd.read_csv(DATA_DIR / "campaign_desc.csv")
ctab = pd.read_csv(DATA_DIR / "campaign_table.csv")
coup = pd.read_csv(DATA_DIR / "coupon.csv")

END, START = tx.DAY.max(), tx.DAY.min()
cdesc = cdesc[(cdesc.START_DAY <= END) & (~cdesc.CAMPAIGN.isin([15, 24]))].copy()
cdesc["END_C"] = cdesc.END_DAY.clip(upper=END)
PRE = 56
all_hh = np.array(sorted(tx.household_key.unique()))


def spend(sub, prods, comms):
    """가구별 (a)대상상품 (b)카테고리 (c)전체 지출 — all_hh 순서로 정렬"""
    g = sub.groupby("household_key").SALES_VALUE.sum()
    a = sub[sub.PRODUCT_ID.isin(prods)].groupby("household_key").SALES_VALUE.sum()
    b = sub[sub.COMMODITY_DESC.isin(comms)].groupby("household_key").SALES_VALUE.sum()
    return (a.reindex(all_hh).fillna(0).values,
            b.reindex(all_hh).fillna(0).values,
            g.reindex(all_hh).fillna(0).values)


def build(r, pre_lo, pre_hi, post_lo, post_hi, prods, comms, tg):
    """한 캠페인의 (가구 × 전후) 패널 — 일평균 지출 변화"""
    n_pre, n_post = pre_hi - pre_lo + 1, post_hi - post_lo + 1
    pa, pb, pc = spend(tx[tx.DAY.between(pre_lo, pre_hi)], prods, comms)
    qa, qb, qc = spend(tx[tx.DAY.between(post_lo, post_hi)], prods, comms)
    d = pd.DataFrame({
        "target": np.isin(all_hh, list(tg)),
        "pre_a": pa / n_pre, "pre_b": pb / n_pre, "pre_c": pc / n_pre,
        "da": qa / n_post - pa / n_pre,
        "db": qb / n_post - pb / n_pre,
        "dc": qc / n_post - pc / n_pre})
    d["stratum"] = pd.qcut(d.pre_c.rank(method="first"), 5, labels=False)
    return d


def did_one(g, col):
    """한 캠페인 안에서 층화별 (타겟변화 - 대조변화)를 타겟 수로 가중평균"""
    t = g.groupby(["stratum", "target"])[col].mean().unstack()
    if True not in t.columns or False not in t.columns:
        return np.nan
    eff = (t[True] - t[False]).dropna()
    n = g[g.target].groupby("stratum").size().reindex(eff.index).fillna(0)
    return float((eff * n).sum() / n.sum()) if n.sum() > 0 else np.nan


real, placebo, panels = [], [], []
for _, r in cdesc.iterrows():
    c = int(r.CAMPAIGN)
    prods = set(coup.loc[coup.CAMPAIGN == c, "PRODUCT_ID"])
    comms = set(pr.loc[pr.PRODUCT_ID.isin(prods), "COMMODITY_DESC"].dropna())
    tg = set(ctab.loc[ctab.CAMPAIGN == c, "household_key"])
    if not tg or r.START_DAY - PRE < START:
        continue

    # 실제: 사전 56일 → 캠페인 기간
    d = build(r, r.START_DAY - PRE, r.START_DAY - 1,
              r.START_DAY, int(r.END_C), prods, comms, tg)
    d["CAMPAIGN"], d["TYPE"] = c, r.DESCRIPTION
    panels.append(d)
    row = {"CAMPAIGN": c, "TYPE": r.DESCRIPTION, "타겟수": int(d.target.sum())}
    for col in ("da", "db", "dc"):
        row[col] = did_one(d, col)
    real.append(row)

    # 플라시보: 캠페인 시작 -112일 → -57일 (개입이 없던 구간)
    if r.START_DAY - 2 * PRE >= START:
        pl = build(r, r.START_DAY - 2 * PRE, r.START_DAY - PRE - 1,
                   r.START_DAY - PRE, r.START_DAY - 1, prods, comms, tg)
        placebo.append({"CAMPAIGN": c,
                        **{col: did_one(pl, col) for col in ("da", "db", "dc")}})

R = pd.DataFrame(real)
P = pd.DataFrame(placebo)
D = pd.concat(panels, ignore_index=True)

p("=" * 70)
p("H2-4 — 쿠폰 증분 매출 검증 (캠페인별 DiD + 사전지출 5분위 층화)")
p("=" * 70)
p(f"캠페인 {len(R)}개 (C15·C24 제외) / 타겟 {R.타겟수.sum():,}건")
p(f"사전 {PRE}일 → 캠페인 기간, 모두 '일평균 지출'로 환산")

NAMES = {"da": "(a) 쿠폰 대상 상품", "db": "(b) 해당 카테고리 전체",
         "dc": "(c) 가구 전체 지출"}
p("\n=== 캠페인별 DiD 분포 (28개 캠페인) ===")
rows = []
for col, name in NAMES.items():
    s = R[col].dropna()
    base = D.loc[D.target, col.replace("d", "pre_")].mean()
    rows.append({"수준": name,
                 "중앙값": round(s.median(), 4),
                 "가중평균": round(np.average(s, weights=R.loc[s.index, "타겟수"]), 4),
                 "양수 캠페인": f"{(s > 0).sum()}/{len(s)}",
                 "타겟 사전수준": round(base, 3),
                 "중앙값 상대효과%": round(s.median() / base * 100, 1)})
p(pd.DataFrame(rows).to_string(index=False))

p("\n=== 플라시보 테스트 (캠페인 없던 가짜 기간) — 0에 가까워야 정상 ===")
prows = []
for col, name in NAMES.items():
    s = P[col].dropna()
    prows.append({"수준": name, "중앙값": round(s.median(), 4),
                  "양수 캠페인": f"{(s > 0).sum()}/{len(s)}"})
p(pd.DataFrame(prows).to_string(index=False))

p("\n=== 타입별 DiD 중앙값 ===")
t = R.groupby("TYPE").agg(캠페인=("CAMPAIGN", "size"), 타겟수=("타겟수", "sum"),
                          a=("da", "median"), b=("db", "median"), c=("dc", "median"))
t.columns = ["캠페인", "타겟수", "(a)상품", "(b)카테고리", "(c)전체"]
p(t.round(4).to_string())

p("\n=== 매칭 점검: 층화 후 사전 지출 비율 (1.0이면 완벽) ===")
chk = D.groupby(["stratum", "target"]).pre_c.mean().unstack()
chk.columns = ["비타겟", "타겟"]
chk["비율"] = (chk["타겟"] / chk["비타겟"]).round(2)
chk["타겟수"] = D[D.target].groupby("stratum").size()
p(chk.round(3).to_string())
p(f"  층화 전 비율: "
  f"{D.loc[D.target,'pre_c'].mean() / D.loc[~D.target,'pre_c'].mean():.2f}배")

R.to_csv("outputs/incremental_did.csv", index=False, encoding="utf-8-sig")
p("\n캠페인별 결과 저장 → outputs/incremental_did.csv")
sys.stdout.buffer.write(out.getvalue().encode("utf-8"))
