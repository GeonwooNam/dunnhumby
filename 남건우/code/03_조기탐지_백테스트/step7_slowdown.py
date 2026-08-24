# -*- coding: utf-8 -*-
"""STEP 7 — 뜸해짐(간격 벌어짐, W51~80 측정)이 홀드아웃(W81~101) 지출 감소의 선행 신호인지 채점.

주의: 기존 step6_early_signal.csv의 '최근 3개 간격'은 홀드아웃 포함 전체 방문으로 계산돼
시간 분리 요건(신호 W51~80, 채점 W81~101)에 어긋난다. 신호를 D558 이전 방문만으로 재계산한다.
그 외 정의(모집단·baseline·고가치·1.5배 기준)는 전부 기존 것 재사용.
"""
import duckdb, pandas as pd, numpy as np, os, json

BASE = "/Users/namgeon-u/Desktop/claude/dunnhumby"
IN = os.path.join(BASE, "0815 2차 회의 준비", "outputs")   # 기존 산출물 (step1_baseline, summary.json)
OUT = os.path.join(BASE, "0815 2차 회의 산출물")            # STEP 7 산출물
DAY_W17_START, DAY_W50_END = 111, 348
DAY_W80_END = 558
DAY_W81_START, DAY_W101_END = 559, 705
WEEKS_BASE, WEEKS_HOLD = 34, 21
EXCL_DEPTS = ("KIOSK-GAS", "MISC SALES TRAN")

con = duckdb.connect(os.path.join(BASE, "data/processed/dunnhumby.duckdb"), read_only=True)
visits = con.execute(f"""
    SELECT t.household_key, t.DAY, SUM(t.SALES_VALUE) AS day_spend
    FROM transaction_data t JOIN product p USING (PRODUCT_ID)
    WHERE p.DEPARTMENT NOT IN {EXCL_DEPTS} AND t.DAY BETWEEN {DAY_W17_START} AND {DAY_W101_END}
    GROUP BY 1,2
""").df()

inc = pd.read_csv(os.path.join(IN, "step1_baseline.csv"))
pop = inc[inc.high_value & ~inc.churned]  # 고가치 정상군
print("모집단(고가치 정상군):", len(pop))

vd = {hh: g.sort_values("DAY") for hh, g in visits.groupby("household_key")}

rows = []
excluded_lt3 = 0
for _, r in pop.iterrows():
    hh = r.household_key
    g = vd[hh]
    days = g.DAY.values
    scan = days[days <= DAY_W80_END]        # 신호는 W51~80 종료 시점까지의 방문만
    gaps = np.diff(scan)
    if len(gaps) < 3:
        excluded_lt3 += 1
        continue
    recent3 = float(np.mean(gaps[-3:]))
    base_spend = float(g[g.DAY <= DAY_W50_END].day_spend.sum())
    hold_spend = float(g[(g.DAY >= DAY_W81_START)].day_spend.sum())
    base_visits_n = int((days <= DAY_W50_END).sum())
    hold_visits_n = int((days >= DAY_W81_START).sum())
    base_wk = base_spend / WEEKS_BASE
    hold_wk = hold_spend / WEEKS_HOLD
    rows.append({
        "household_key": hh, "median_gap": r.median_gap,
        "recent3_mean_gap_w5180": recent3,
        "widen_15": recent3 >= 1.5 * r.median_gap,
        "widen_20": recent3 >= 2.0 * r.median_gap,
        "base_weekly_spend": base_wk, "hold_weekly_spend": hold_wk,
        "retention": hold_wk / base_wk,
        "base_spend_total": base_spend,
        "base_visits": base_visits_n, "hold_visits": hold_visits_n,
        "base_spend_per_visit": base_spend / base_visits_n,
        "hold_spend_per_visit": hold_spend / hold_visits_n if hold_visits_n else np.nan,
    })
s7 = pd.DataFrame(rows)
print("신호 판정 가능:", len(s7), "/ 간격<3 제외:", excluded_lt3)
s7.to_csv(os.path.join(OUT, "step7_slowdown_score.csv"), index=False)

def summarize(df, flag_col):
    out = []
    for label, sub in [("벌어짐", df[df[flag_col]]), ("유지", df[~df[flag_col]])]:
        ret = sub.retention
        drop70 = (ret < 0.70)
        out.append({
            "신호임계": flag_col, "그룹": label, "n": len(sub),
            "유지율_중앙값": ret.median(), "p25": ret.quantile(0.25), "p75": ret.quantile(0.75),
            "유지율_평균": ret.mean(), "유지율_SE": ret.std(ddof=1) / np.sqrt(len(sub)),
            "70pct미만_가구비율": drop70.mean(), "70pct미만_n": int(drop70.sum()),
            "baseline_주당지출_중앙값": sub.base_weekly_spend.median(),
            "baseline_총지출_합": sub.base_spend_total.sum(),
            "방문당지출_변화_중앙값": (sub.hold_spend_per_visit / sub.base_spend_per_visit).median(),
        })
    return pd.DataFrame(out)

summ = pd.concat([summarize(s7, "widen_15"), summarize(s7, "widen_20")])
summ.to_csv(os.path.join(OUT, "step7_summary.csv"), index=False)
print(summ.to_string(index=False))

# 차이 + 단순 SE
def diff_stats(df, flag_col):
    a, b = df[df[flag_col]], df[~df[flag_col]]
    p1, p2 = (a.retention < 0.70).mean(), (b.retention < 0.70).mean()
    se_p = np.sqrt(p1*(1-p1)/len(a) + p2*(1-p2)/len(b))
    m1, m2 = a.retention.mean(), b.retention.mean()
    se_m = np.sqrt(a.retention.var(ddof=1)/len(a) + b.retention.var(ddof=1)/len(b))
    return {"threshold": flag_col, "n_widen": len(a), "n_keep": len(b),
            "drop70_diff_pp": (p1-p2)*100, "drop70_diff_se_pp": se_p*100,
            "mean_ret_diff": m1-m2, "mean_ret_diff_se": se_m,
            "median_ret_widen": float(a.retention.median()), "median_ret_keep": float(b.retention.median())}
d15, d20 = diff_stats(s7, "widen_15"), diff_stats(s7, "widen_20")
print(d15); print(d20)

# 보조 4: 벌어짐(1.5) 그룹 내 지출 유지(>=70%) vs 하락(<70%) baseline 특성
w = s7[s7.widen_15]
aux = []
for label, sub in [("유지(>=70%)", w[w.retention >= 0.70]), ("하락(<70%)", w[w.retention < 0.70])]:
    aux.append({"구분": label, "n": len(sub),
                "baseline_중앙간격_중앙값": sub.median_gap.median(),
                "baseline_방문수_중앙값": sub.base_visits.median(),
                "baseline_주당지출_중앙값": sub.base_weekly_spend.median(),
                "recent3배율_중앙값": (sub.recent3_mean_gap_w5180 / sub.median_gap).median()})
aux = pd.DataFrame(aux)
aux.to_csv(os.path.join(OUT, "step7_aux_within_widen.csv"), index=False)
print(aux.to_string(index=False))

# viz용
s7[["household_key", "widen_15", "widen_20", "retention"]].to_csv(
    os.path.join(OUT, "viz_step7_retention.csv"), index=False)

# summary.json에 step7 추가
sj_path = os.path.join(IN, "summary.json")
sj = json.load(open(sj_path))
sj["step7"] = {
    "note": "신호는 W51~80 방문만으로 재계산 (기존 step6은 홀드아웃 포함이라 시간 분리 위반)",
    "population": int(len(pop)), "scored": int(len(s7)), "excluded_lt3gaps": int(excluded_lt3),
    "diff_15": d15, "diff_20": d20,
    "summary": summ.to_dict("records"),
    "aux_within_widen": aux.to_dict("records"),
}
json.dump(sj, open(sj_path, "w"), ensure_ascii=False, indent=2, default=str)
print("saved.")
