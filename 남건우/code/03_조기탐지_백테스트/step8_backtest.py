# -*- coding: utf-8 -*-
"""STEP 8 — 지출 감소 '조기 탐지' 백테스트.

과녁: 홀드아웃 주당 지출 < baseline의 70% (STEP 7 라벨 재사용, 이탈 라벨 사용 안 함)
A. 주 단위 롤링 신호(간격 배율) vs 지출 하락 시작점의 리드타임
B. 운영형 규칙(개인화 x2.0 경보 + 7일 무복귀)을 새 과녁으로 채점
C. 카테고리 폭 축소 신호 (스트레치)
+ §1 표 재검증 (x3.0 스냅샷, 기존 경보 '한 번이라도')

시간 규율: 주차 w의 신호는 w 종료일까지의 방문만 사용 (미래 혼입 금지).
하락 판정은 신호와 독립적으로 지출 시계열에서만 산출하고,
'조기'는 lead > 0 (신호 주 < 하락 시작 주)만 인정, 동시 발화(lead=0)는 별도 보고.
"""
import duckdb, pandas as pd, numpy as np, os, json, math

BASE = "/Users/namgeon-u/Desktop/claude/dunnhumby"
IN = os.path.join(BASE, "0815 2차 회의 준비", "outputs")
OUT = os.path.join(BASE, "0815 회의 준비 3번")
EXCL_DEPTS = ("KIOSK-GAS", "MISC SALES TRAN")
W_BASE_START, W_BASE_END = 17, 50
W_EVAL_START, W_EVAL_END = 51, 80
W_HOLD_START, W_HOLD_END = 81, 101
WEEKS_BASE, WEEKS_HOLD = 34, 21
DAY_W80_END = 558
def week_end_day(w): return 7 * w - 2

con = duckdb.connect(os.path.join(BASE, "data/processed/dunnhumby.duckdb"), read_only=True)

inc = pd.read_csv(os.path.join(IN, "step1_baseline.csv"))
pop = inc[inc.high_value & ~inc.churned].copy()  # 고가치 정상군 400
med = pop.set_index("household_key").median_gap.to_dict()
hhs = list(pop.household_key)
print("모집단:", len(pop))

# ---------- 공통 재료 ----------
visits = con.execute(f"""
    SELECT t.household_key, t.DAY, SUM(t.SALES_VALUE) AS day_spend
    FROM transaction_data t JOIN product p USING (PRODUCT_ID)
    WHERE p.DEPARTMENT NOT IN {EXCL_DEPTS} AND t.DAY BETWEEN 111 AND 705
      AND t.household_key IN {tuple(hhs)}
    GROUP BY 1,2
""").df()
vd = {hh: g.sort_values("DAY") for hh, g in visits.groupby("household_key")}

wk_spend = con.execute(f"""
    SELECT t.household_key, t.WEEK_NO, SUM(t.SALES_VALUE) AS spend
    FROM transaction_data t JOIN product p USING (PRODUCT_ID)
    WHERE p.DEPARTMENT NOT IN {EXCL_DEPTS} AND t.WEEK_NO BETWEEN 17 AND 101
      AND t.household_key IN {tuple(hhs)}
    GROUP BY 1,2
""").df()
sp = {hh: g.set_index("WEEK_NO").spend.reindex(range(17, 102), fill_value=0.0)
      for hh, g in wk_spend.groupby("household_key")}

base_weekly = {hh: float(sp[hh].loc[17:50].sum() / WEEKS_BASE) for hh in hhs}
hold_weekly = {hh: float(sp[hh].loc[81:101].sum() / WEEKS_HOLD) for hh in hhs}
drop70 = {hh: hold_weekly[hh] / base_weekly[hh] < 0.70 for hh in hhs}
n_drop = sum(drop70.values())
print(f"과녁 base rate: {n_drop}/{len(hhs)} = {n_drop/len(hhs):.3f}")

# ---------- §1 재검증 ----------
def snapshot_ratio(hh):
    days = vd[hh].DAY.values
    scan = days[days <= DAY_W80_END]
    gaps = np.diff(scan)
    return float(np.mean(gaps[-3:])) / med[hh] if len(gaps) >= 3 else np.nan

snap = {hh: snapshot_ratio(hh) for hh in hhs}
al = pd.read_csv(os.path.join(IN, "step2_alerts_thr2.csv"))
alert_ever = set(al[al.first_alert.notna()].household_key) & set(hhs)

verify_rows = []
def score_signal(name, pos_set):
    tp = sum(1 for h in pos_set if drop70[h])
    prec = tp / len(pos_set) if pos_set else np.nan
    rec = tp / n_drop
    verify_rows.append({"신호": name, "양성": len(pos_set), "TP": tp,
                        "precision": prec, "recall": rec,
                        "lift": prec / (n_drop / len(hhs))})
for thr in [1.5, 2.0, 3.0]:
    score_signal(f"뜸해짐 x{thr}", {h for h in hhs if snap[h] >= thr})
score_signal("기존 경보 한 번이라도", alert_ever)

# ---------- 과제 A: 리드타임 ----------
# 지출 하락 시작 주: rolling4(w) = 직전 4주(w-3..w) 평균지출/baseline 주당지출 이
# 처음 0.7 미만이고, 이후 4주(w+1..w+4) 중 3주 이상 0.7 미만 유지. w<=97만 판정 가능.
def drop_start_week(hh):
    s = sp[hh]
    bw = base_weekly[hh]
    roll = {w: s.loc[w-3:w].mean() / bw for w in range(51, 102)}
    for w in range(51, 98):
        if roll[w] < 0.7 and sum(roll[u] < 0.7 for u in range(w+1, w+5)) >= 3:
            return w
    return None

# 신호 발화 주: w 종료일까지의 방문으로 최근 3개 간격 평균/중앙간격 >= thr 가 처음 참인 주
def signal_week(hh, thr):
    days = vd[hh].DAY.values
    m = med[hh]
    for w in range(51, 102):
        scan = days[days <= week_end_day(w)]
        gaps = np.diff(scan)
        if len(gaps) >= 3 and np.mean(gaps[-3:]) >= thr * m:
            return w
    return None

lead_rows = []
for hh in hhs:
    dw = drop_start_week(hh)
    row = {"household_key": hh, "drop_week": dw, "dropped_rolling": dw is not None,
           "drop70_holdout": drop70[hh]}
    for thr in [1.5, 2.0, 2.5]:
        sw = signal_week(hh, thr)
        row[f"sig_week_{thr}"] = sw
        row[f"lead_{thr}"] = (dw - sw) if (dw is not None and sw is not None) else None
    lead_rows.append(row)
lead = pd.DataFrame(lead_rows)
lead.to_csv(os.path.join(OUT, "step8_leadtime.csv"), index=False)

lead_summary = []
dropped = lead[lead.dropped_rolling]
print("롤링 하락 가구:", len(dropped))
for thr in [1.5, 2.0, 2.5]:
    sub = dropped[dropped[f"sig_week_{thr}"].notna()]
    ld = sub[f"lead_{thr}"].astype(float)
    early = ld[ld > 0]
    lead_summary.append({
        "임계": thr, "하락가구": len(dropped), "신호발화(커버)": len(sub),
        "커버율": len(sub) / len(dropped),
        "신호가_먼저(lead>0)": int((ld > 0).sum()), "먼저_비율": float((ld > 0).mean()),
        "동시(lead=0)": int((ld == 0).sum()), "동시_비율": float((ld == 0).mean()),
        "신호가_늦음(lead<0)": int((ld < 0).sum()),
        "lead_중앙(먼저인_가구)": float(early.median()) if len(early) else None,
        "lead_p25": float(early.quantile(0.25)) if len(early) else None,
        "lead_p75": float(early.quantile(0.75)) if len(early) else None,
        "lead_중앙(전체발화)": float(ld.median()),
    })
lead_summ = pd.DataFrame(lead_summary)
print(lead_summ.to_string(index=False))
lead[["household_key", "drop_week", "sig_week_1.5", "lead_1.5", "sig_week_2.0", "lead_2.0"]].to_csv(
    os.path.join(OUT, "viz_step8_leadtime.csv"), index=False)

# ---------- 과제 B: 운영형 규칙 채점 ----------
ep = pd.read_csv(os.path.join(IN, "supp_episodes_thr2.csv"))
ep = ep[ep.household_key.isin(hhs)]
def no_return_7d(hh, a):
    days = vd[hh].DAY.values
    return not np.any((days > a) & (days <= a + 7))
ep["confirmed_7d"] = [no_return_7d(r.household_key, r.alert_day) for r in ep.itertuples()]
conf = ep[ep.confirmed_7d]
rule_pos = set(conf.household_key)
score_signal("경보 x2.0 + 7일 무복귀", rule_pos)
vol_week = conf.groupby("week").size()
rule_volume = {"확인성립_에피소드": int(len(conf)), "주당_중앙값": float(vol_week.median()),
               "가구수": len(rule_pos)}
print("7일 무복귀 볼륨:", rule_volume)

verify = pd.DataFrame(verify_rows)
verify.to_csv(os.path.join(OUT, "step8_rule_score.csv"), index=False)
print(verify.to_string(index=False))

# ---------- 과제 C: 카테고리 폭 축소 ----------
wk_cats = con.execute(f"""
    SELECT t.household_key, t.WEEK_NO, COUNT(DISTINCT p.COMMODITY_DESC) AS n_cats,
           LIST(DISTINCT p.COMMODITY_DESC) AS cats
    FROM transaction_data t JOIN product p USING (PRODUCT_ID)
    WHERE p.DEPARTMENT NOT IN {EXCL_DEPTS} AND t.WEEK_NO BETWEEN 17 AND 101
      AND t.household_key IN {tuple(hhs)}
    GROUP BY 1,2
""").df()
cat_sets = {}
for r in wk_cats.itertuples():
    cat_sets.setdefault(r.household_key, {})[r.WEEK_NO] = set(r.cats)

def cats_8w(hh, w_end):
    s = set()
    d = cat_sets.get(hh, {})
    for w in range(w_end - 7, w_end + 1):
        s |= d.get(w, set())
    return len(s)

cat_rows = []
for hh in hhs:
    base_avg = np.mean([cats_8w(hh, w) for w in range(24, 51)])
    eval_end = cats_8w(hh, 80)  # 스냅샷: 평가기간 말(W73~80)
    ratio = eval_end / base_avg if base_avg else np.nan
    cat_rows.append({"household_key": hh, "base_8w_avg_cats": base_avg,
                     "eval_end_8w_cats": eval_end, "cat_ratio": ratio,
                     "cat_fire": ratio < 0.7,
                     "widen_15": snap[hh] >= 1.5, "drop70": drop70[hh]})
cat = pd.DataFrame(cat_rows)
cat.to_csv(os.path.join(OUT, "step8_category_signal.csv"), index=False)

combo_rows = []
for name, mask in [("카테고리 축소 단독", cat.cat_fire),
                   ("간격 x1.5 단독", cat.widen_15),
                   ("둘 다 발화", cat.cat_fire & cat.widen_15),
                   ("간격만 (카테고리 미발화)", cat.widen_15 & ~cat.cat_fire),
                   ("카테고리만 (간격 미발화)", cat.cat_fire & ~cat.widen_15)]:
    sub = cat[mask]
    tp = int(sub.drop70.sum())
    combo_rows.append({"신호": name, "양성": len(sub), "TP": tp,
                       "precision": tp / len(sub) if len(sub) else np.nan,
                       "recall": tp / n_drop})
combo = pd.DataFrame(combo_rows)
combo.to_csv(os.path.join(OUT, "step8_category_combo.csv"), index=False)
print(combo.to_string(index=False))

# ---------- summary.json step8 키 ----------
sj_path = os.path.join(IN, "summary.json")
sj = json.load(open(sj_path))
sj["step8"] = {
    "base_rate_drop70": {"n": n_drop, "N": len(hhs)},
    "verify_and_rule": verify.to_dict("records"),
    "rule_volume": rule_volume,
    "lead": lead_summ.to_dict("records"),
    "n_dropped_rolling": int(len(dropped)),
    "category_combo": combo.to_dict("records"),
}
json.dump(sj, open(sj_path, "w"), ensure_ascii=False, indent=2, default=str)
print("saved.")
