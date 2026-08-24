# -*- coding: utf-8 -*-
"""분기 A 대응 보조 분석: (1) 스캔 종료 시점 '경보 지속 중' 스냅샷 채점,
(2) 오탐 가구의 복귀 속도, (3) 주별 에피소드 볼륨, (4) 이탈자 점진형/절벽형 비율"""
import duckdb, pandas as pd, numpy as np, math, os, json

BASE = "/Users/namgeon-u/Desktop/claude/dunnhumby"
OUT = os.path.join(BASE, "0815 2차 회의 준비", "outputs")
DAY_W17_START, DAY_W50_END = 111, 348
DAY_W51_START, DAY_W80_END = 349, 558
DAY_W81_START, DAY_W101_END = 559, 705
EXCL_DEPTS = ("KIOSK-GAS", "MISC SALES TRAN")

con = duckdb.connect(os.path.join(BASE, "data/processed/dunnhumby.duckdb"), read_only=True)
visits = con.execute(f"""
    SELECT t.household_key, t.DAY
    FROM transaction_data t JOIN product p USING (PRODUCT_ID)
    WHERE p.DEPARTMENT NOT IN {EXCL_DEPTS} AND t.DAY BETWEEN {DAY_W17_START} AND {DAY_W101_END}
    GROUP BY 1,2
""").df()
vd = {hh: np.sort(g.DAY.values) for hh, g in visits.groupby("household_key")}

inc = pd.read_csv(os.path.join(OUT, "step1_baseline.csv"))
med = inc.set_index("household_key").median_gap.to_dict()
hv = inc.set_index("household_key").high_value.to_dict()
churn = inc.set_index("household_key").churned.to_dict()
inc_set = list(inc.household_key)

# (1) 스냅샷 채점: 관측 종료일(D558) 기준 '경보 상태 지속 중' 가구
snap_rows = []
for thr in [1.5, 2.0, 2.5, 3.0]:
    for name in ["전체", "고가치"]:
        hhs = [h for h in inc_set if (name == "전체" or hv[h])]
        tp = fp = fn = tn = 0
        for h in hhs:
            days = vd[h]
            scan = days[days <= DAY_W80_END]
            elapsed = DAY_W80_END - (int(scan[-1]) if len(scan) else DAY_W17_START)
            on = elapsed > thr * med[h]
            c = churn[h]
            tp += on and c; fp += on and not c; fn += (not on) and c; tn += (not on) and (not c)
        snap_rows.append({"rule": f"개인화 x{thr}", "group": name, "alert_on": tp + fp,
                          "TP": tp, "FP": fp, "FN": fn,
                          "precision": tp / (tp + fp) if tp + fp else np.nan,
                          "recall": tp / (tp + fn) if tp + fn else np.nan, "n": len(hhs)})
# 근하 35일 스냅샷 (동일 시점)
for name in ["전체", "고가치"]:
    hhs = [h for h in inc_set if (name == "전체" or hv[h])]
    tp = fp = fn = tn = 0
    for h in hhs:
        days = vd[h]
        scan = days[days <= DAY_W80_END]
        elapsed = DAY_W80_END - (int(scan[-1]) if len(scan) else DAY_W17_START)
        on = elapsed >= 35
        c = churn[h]
        tp += on and c; fp += on and not c; fn += (not on) and c; tn += (not on) and (not c)
    snap_rows.append({"rule": "35일 일괄", "group": name, "alert_on": tp + fp,
                      "TP": tp, "FP": fp, "FN": fn,
                      "precision": tp / (tp + fp) if tp + fp else np.nan,
                      "recall": tp / (tp + fn) if tp + fn else np.nan, "n": len(hhs)})
snap = pd.DataFrame(snap_rows)
snap.to_csv(os.path.join(OUT, "supp_snapshot_d558.csv"), index=False)
print(snap.to_string(index=False))

# (2) 오탐(복귀) 가구: 첫 경보 → 복귀까지 걸린 날
al = pd.read_csv(os.path.join(OUT, "step2_alerts_thr2.csv"))
ret_days = []
for _, r in al[~al.churned].iterrows():
    days = vd[r.household_key]
    after = days[days > r.first_alert]
    if len(after):
        ret_days.append(int(after[0] - r.first_alert))
ret_days = np.array(ret_days)
ret_stats = {"n": int(len(ret_days)), "median": float(np.median(ret_days)),
             "p75": float(np.percentile(ret_days, 75)), "p90": float(np.percentile(ret_days, 90)),
             "within7_share": float((ret_days <= 7).mean()), "within14_share": float((ret_days <= 14).mean())}
print("오탐 복귀 속도:", ret_stats)

# (3) 주별 에피소드 볼륨 (thr 2.0, 전 에피소드)
ep_rows = []
for h in inc_set:
    m = med[h]
    days = vd[h]
    scan = list(days[days <= DAY_W80_END]) + [None]
    for i in range(len(scan) - 1):
        v, nxt = scan[i], scan[i + 1]
        raw = math.floor(v + 2.0 * m) + 1
        eff = max(raw, DAY_W51_START)
        if nxt is not None and eff >= nxt: continue
        if eff > DAY_W80_END: continue
        ep_rows.append({"household_key": h, "alert_day": eff, "week": (eff - 1) // 7 + 1,
                        "high_value": hv[h]})
ep = pd.DataFrame(ep_rows)
wk = ep.groupby("week").size()
wk_hv = ep[ep.high_value].groupby("week").size()
vol = {"episodes_per_week_median_excl_first": float(wk[wk.index > 51].median()),
       "episodes_per_week_first_week": int(wk.iloc[0]),
       "hv_episodes_per_week_median_excl_first": float(wk_hv[wk_hv.index > 51].median())}
ep.to_csv(os.path.join(OUT, "supp_episodes_thr2.csv"), index=False)
print("주별 에피소드:", vol)

# (4) 이탈자 36곳 점진형/절벽형: 마지막 방문 전 3개 간격 평균 >= 1.5x baseline?
pat_rows = []
for h in inc_set:
    if not churn[h]: continue
    days = vd[h]
    scan = days[days <= DAY_W80_END]
    gaps = np.diff(scan)
    if len(gaps) < 3:
        pat = "판별불가(간격<3)"
    else:
        pat = "점진형" if np.mean(gaps[-3:]) >= 1.5 * med[h] else "절벽형"
    pat_rows.append({"household_key": h, "pattern": pat, "high_value": hv[h]})
pat = pd.DataFrame(pat_rows)
print(pat.pattern.value_counts().to_dict())
pat.to_csv(os.path.join(OUT, "supp_churn_pattern.csv"), index=False)

json.dump({"ret_stats": ret_stats, "vol": vol,
           "churn_pattern": pat.pattern.value_counts().to_dict()},
          open(os.path.join(OUT, "supp_summary.json"), "w"), ensure_ascii=False, indent=2)
