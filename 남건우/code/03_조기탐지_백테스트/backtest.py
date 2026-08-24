# -*- coding: utf-8 -*-
"""
리텐션 규칙 백테스트 — "간격이 평소 2배 초과 시 경보"
README_claude_code.md 지시서 STEP 1~6 구현.

파라미터 (기본값):
- 분석구간 W17~W101 (DAY 111~705), 비장보기 부문(KIOSK-GAS, MISC SALES TRAN) 제외
- 기준기간 W17~W50 (DAY 111~348)
- 평가기간 W51~W80 (DAY 349~558)
- 홀드아웃 W81~W101 (DAY 559~705), 재방문 없음 = 이탈
- 경보 임계: 개인 baseline 방문간격 중앙값 × {1.5, 2.0, 2.5, 3.0}, 기본 2.0
- baseline 최소 방문 수 8회
- 고가치 = baseline 총지출 상위 20% (근하 방식과 동일하게 지출 20% 컷)
"""
import duckdb
import pandas as pd
import numpy as np
import math
import os
import json

BASE = "/Users/namgeon-u/Desktop/claude/dunnhumby"
OUT = os.path.join(BASE, "0815 2차 회의 준비", "outputs")
os.makedirs(OUT, exist_ok=True)

DAY_W17_START, DAY_W50_END = 111, 348   # baseline
DAY_W51_START, DAY_W80_END = 349, 558   # evaluation (경보 스캔)
DAY_W81_START, DAY_W101_END = 559, 705  # holdout (채점)
EXCL_DEPTS = ("KIOSK-GAS", "MISC SALES TRAN")
THRESHOLDS = [1.5, 2.0, 2.5, 3.0]
MIN_BASELINE_VISITS = 8

con = duckdb.connect(os.path.join(BASE, "data/processed/dunnhumby.duckdb"), read_only=True)

# ---------- 공통 전처리: 장보기 방문(일 단위) ----------
visits = con.execute(f"""
    SELECT t.household_key, t.DAY,
           MIN(t.WEEK_NO) AS week_no,
           SUM(t.SALES_VALUE) AS day_spend,
           COUNT(DISTINCT t.BASKET_ID) AS n_baskets
    FROM transaction_data t
    JOIN product p USING (PRODUCT_ID)
    WHERE p.DEPARTMENT NOT IN {EXCL_DEPTS}
      AND t.DAY BETWEEN {DAY_W17_START} AND {DAY_W101_END}
    GROUP BY 1, 2
""").df()

n_hh_all = visits["household_key"].nunique()

# ---------- STEP 1: baseline ----------
base_v = visits[visits.DAY <= DAY_W50_END]
rows = []
for hh, g in base_v.groupby("household_key"):
    days = np.sort(g.DAY.values)
    gaps = np.diff(days)
    rows.append({
        "household_key": hh,
        "base_visits": len(days),
        "base_spend": g.day_spend.sum(),
        "median_gap": float(np.median(gaps)) if len(gaps) > 0 else np.nan,
        "p90_gap": float(np.percentile(gaps, 90)) if len(gaps) > 0 else np.nan,
        "gap_iqr": float(np.percentile(gaps, 75) - np.percentile(gaps, 25)) if len(gaps) > 0 else np.nan,
    })
base = pd.DataFrame(rows)

n_hh_with_baseline = len(base)
included = base[base.base_visits >= MIN_BASELINE_VISITS].copy()
n_excluded_lowvisits = n_hh_with_baseline - len(included)
n_excluded_no_baseline = n_hh_all - n_hh_with_baseline  # W51 이후에만 등장한 가구

# 고가치 = baseline 지출 상위 20%
cut = included.base_spend.quantile(0.80)
included["high_value"] = included.base_spend >= cut

# baseline 간격 분포 (근하 대조: 중앙값 4, p90 14)
all_gaps = []
for hh, g in base_v[base_v.household_key.isin(included.household_key)].groupby("household_key"):
    all_gaps.append(np.diff(np.sort(g.DAY.values)))
all_gaps = np.concatenate(all_gaps)
gap_dist = {
    "n_gaps": int(len(all_gaps)),
    "median": float(np.median(all_gaps)),
    "p75": float(np.percentile(all_gaps, 75)),
    "p90": float(np.percentile(all_gaps, 90)),
    "mean": float(np.mean(all_gaps)),
}

# ---------- 방문 시퀀스 (스캔용 W17~80, 홀드아웃 W81~101) ----------
vd = {hh: np.sort(g.DAY.values) for hh, g in visits.groupby("household_key")}
inc_set = set(included.household_key)
med = included.set_index("household_key").median_gap.to_dict()
hv = included.set_index("household_key").high_value.to_dict()

# 이탈 라벨: W81~101 재방문 없음
churn = {}
for hh in inc_set:
    days = vd[hh]
    churn[hh] = not np.any((days >= DAY_W81_START) & (days <= DAY_W101_END))
included["churned"] = included.household_key.map(churn)

# ---------- STEP 2: 경보 가상 발생 ----------
def simulate(hh, thr):
    """평가기간 내 경보 에피소드. returns (first_alert_day, n_episodes, backlog_flag)"""
    m = med[hh]
    days = vd[hh]
    scan_days = days[days <= DAY_W80_END]
    episodes = []
    backlog = False
    # 연속 방문 쌍 + 마지막 방문 이후 개방 구간
    pts = list(scan_days) + [None]
    for i in range(len(pts) - 1):
        v = pts[i]
        nxt = pts[i + 1]
        raw_alert = math.floor(v + thr * m) + 1  # 경과일 > thr*m 이 처음 참이 되는 날
        eff = max(raw_alert, DAY_W51_START)      # 규칙 가동 시작일 이전이면 가동일에 발화
        if nxt is not None and eff >= nxt:
            continue  # 경보 전에 복귀
        if eff > DAY_W80_END:
            continue  # 평가기간 밖 (우측 절단)
        episodes.append(eff)
        if raw_alert < DAY_W51_START:
            backlog = True
    if not episodes:
        return None, 0, False
    return episodes[0], len(episodes), backlog

sim = {}
for thr in THRESHOLDS:
    recs = []
    for hh in inc_set:
        fa, nep, backlog = simulate(hh, thr)
        recs.append({"household_key": hh, "first_alert": fa, "n_episodes": nep, "backlog": backlog})
    sim[thr] = pd.DataFrame(recs)

# ---------- STEP 3: 채점 ----------
def score(df_alert):
    d = df_alert.merge(included[["household_key", "high_value", "churned"]], on="household_key")
    out = {}
    for name, sub in [("전체", d), ("고가치", d[d.high_value])]:
        alerted = sub.first_alert.notna()
        tp = int((alerted & sub.churned).sum())
        fp = int((alerted & ~sub.churned).sum())
        fn = int((~alerted & sub.churned).sum())
        tn = int((~alerted & ~sub.churned).sum())
        out[name] = {
            "n": len(sub), "alerted": tp + fp, "churned": tp + fn,
            "TP": tp, "FP": fp, "FN": fn, "TN": tn,
            "precision": tp / (tp + fp) if tp + fp else np.nan,
            "recall": tp / (tp + fn) if tp + fn else np.nan,
        }
    return out

scores = {thr: score(sim[thr]) for thr in THRESHOLDS}

pr_rows = []
for thr in THRESHOLDS:
    for grp, s in scores[thr].items():
        pr_rows.append({"threshold": thr, "group": grp, **s})
pr = pd.DataFrame(pr_rows)
pr.to_csv(os.path.join(OUT, "step3_precision_recall.csv"), index=False)

# 주당 경보 볼륨 (thr=2.0, 첫 경보 기준 + 전체 에피소드)
d2 = sim[2.0].merge(included[["household_key", "high_value", "churned"]], on="household_key")
alerted2 = d2[d2.first_alert.notna()].copy()
alerted2["alert_week"] = ((alerted2.first_alert - 1) // 7 + 1).astype(int)
vol_week = alerted2.groupby("alert_week").size()
n_weeks_eval = 30
volume = {
    "total_first_alerts": int(len(alerted2)),
    "first_alerts_per_week": float(len(alerted2) / n_weeks_eval),
    "total_episodes": int(d2.n_episodes.sum()),
    "episodes_per_week": float(d2.n_episodes.sum() / n_weeks_eval),
    "backlog_day1_alerts": int(d2.backlog.sum()),
    "high_value_share_of_alerts": float(alerted2.high_value.mean()),
    "hv_first_alerts": int(alerted2.high_value.sum()),
    "hv_first_alerts_per_week": float(alerted2.high_value.sum() / n_weeks_eval),
}
alerted2.to_csv(os.path.join(OUT, "step2_alerts_thr2.csv"), index=False)

# 오탐 특성 (thr=2.0): 경보 후 복귀(비이탈) vs 실제 이탈 가구의 baseline 특성
fa_char = alerted2.merge(base[["household_key", "median_gap", "gap_iqr"]], on="household_key")
fp_grp = fa_char[~fa_char.churned]
tp_grp = fa_char[fa_char.churned]
fp_profile = pd.DataFrame({
    "구분": ["오탐(복귀)", "정탐(이탈)"],
    "n": [len(fp_grp), len(tp_grp)],
    "baseline_중앙간격_중앙값": [fp_grp.median_gap.median(), tp_grp.median_gap.median()],
    "간격IQR_중앙값": [fp_grp.gap_iqr.median(), tp_grp.gap_iqr.median()],
    "간격IQR/중앙간격_중앙값": [(fp_grp.gap_iqr / fp_grp.median_gap).median(),
                                (tp_grp.gap_iqr / tp_grp.median_gap).median()],
    "baseline_방문수_중앙값": [
        included.set_index("household_key").loc[fp_grp.household_key].base_visits.median(),
        included.set_index("household_key").loc[tp_grp.household_key].base_visits.median()],
})
fp_profile.to_csv(os.path.join(OUT, "step3_fp_profile.csv"), index=False)

# 오탐의 경보 주차 분포 (계절성 확인)
fp_week = fa_char[~fa_char.churned].groupby("alert_week").size().rename("fp")
tp_week = fa_char[fa_char.churned].groupby("alert_week").size().rename("tp")
week_dist = pd.concat([fp_week, tp_week], axis=1).fillna(0).astype(int)
week_dist.to_csv(os.path.join(OUT, "step3_alert_week_dist.csv"))

# ---------- STEP 4: 35일 규칙 대비 리드타임 ----------
# 이탈자의 마지막 방문(L, W17~80 내) 기준: 본 규칙 최종 에피소드 경보일 vs L+35
lead_rows = []
for hh in inc_set:
    if not churn[hh]:
        continue
    days = vd[hh]
    scan = days[days <= DAY_W80_END]
    if len(scan) == 0:
        continue
    L = int(scan[-1])
    m = med[hh]
    rule_day = max(math.floor(L + 2.0 * m) + 1, DAY_W51_START)
    day35 = L + 35
    lead_rows.append({
        "household_key": hh, "last_visit": L, "median_gap": m,
        "rule_alert_day": rule_day, "day35_alert_day": day35,
        "lead_days": day35 - rule_day,  # +면 본 규칙이 빠름
        "rule_in_window": rule_day <= DAY_W80_END,
        "day35_in_window": day35 <= DAY_W80_END,
        "high_value": hv[hh],
    })
lead = pd.DataFrame(lead_rows)
lead["gap_group"] = pd.cut(lead.median_gap, [0, 4, 7, 14, np.inf],
                           labels=["~4일(고빈도)", "5~7일", "8~14일", "15일+(저빈도)"])
lead.to_csv(os.path.join(OUT, "step4_leadtime.csv"), index=False)

lead_summary = lead.groupby("gap_group", observed=True).agg(
    n=("lead_days", "size"),
    lead_median=("lead_days", "median"),
    lead_p25=("lead_days", lambda x: x.quantile(0.25)),
    lead_p75=("lead_days", lambda x: x.quantile(0.75)),
    rule_earlier_share=("lead_days", lambda x: (x > 0).mean()),
).reset_index()
lead_summary.to_csv(os.path.join(OUT, "step4_leadtime_summary.csv"), index=False)

# ---------- STEP 5: 경보 이후 개입 노출 (기술 비교) ----------
camp = con.execute("""
    SELECT ct.household_key, ct.CAMPAIGN, cd.START_DAY, cd.END_DAY
    FROM campaign_table ct JOIN campaign_desc cd USING (CAMPAIGN, DESCRIPTION)
""").df()
redempt = con.execute("SELECT household_key, DAY FROM coupon_redempt").df()

# 홈스토어(기준기간 장바구니 최다 점포), 선호상품(기준기간 2개 이상 장바구니에서 구매)
homestore = con.execute(f"""
    WITH b AS (
        SELECT t.household_key, t.STORE_ID, COUNT(DISTINCT t.BASKET_ID) AS nb
        FROM transaction_data t JOIN product p USING (PRODUCT_ID)
        WHERE p.DEPARTMENT NOT IN {EXCL_DEPTS}
          AND t.DAY BETWEEN {DAY_W17_START} AND {DAY_W50_END}
        GROUP BY 1, 2
    )
    SELECT household_key, STORE_ID AS home_store
    FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY household_key ORDER BY nb DESC, STORE_ID) rn FROM b)
    WHERE rn = 1
""").df()

pref = con.execute(f"""
    SELECT t.household_key, t.PRODUCT_ID
    FROM transaction_data t JOIN product p USING (PRODUCT_ID)
    WHERE p.DEPARTMENT NOT IN {EXCL_DEPTS}
      AND t.DAY BETWEEN {DAY_W17_START} AND {DAY_W50_END}
    GROUP BY 1, 2
    HAVING COUNT(DISTINCT t.BASKET_ID) >= 2
""").df()

# 경보 가구별 노출 윈도우: 경보일 ~ (경보 후 첫 방문일 or 관측 종료 705)
step5_rows = []
for _, r in alerted2.iterrows():
    hh = r.household_key
    a = int(r.first_alert)
    days = vd[hh]
    after = days[days > a]
    w_end = int(after[0]) if len(after) else DAY_W101_END
    step5_rows.append({"household_key": hh, "alert_day": a, "window_end": w_end,
                       "returned_after_alert": len(after) > 0,
                       "churned": r.churned, "high_value": r.high_value})
s5 = pd.DataFrame(step5_rows)

# 캠페인 수신: 캠페인 기간이 윈도우와 겹침
camp_m = s5.merge(camp, on="household_key", how="left")
camp_m["hit"] = (camp_m.START_DAY <= camp_m.window_end) & (camp_m.END_DAY >= camp_m.alert_day)
camp_hit = camp_m.groupby("household_key").hit.any().rename("campaign_in_window")
s5 = s5.merge(camp_hit, on="household_key", how="left")
s5["campaign_in_window"] = s5.campaign_in_window.fillna(False)

# 쿠폰 사용: 윈도우 내 redemption
red_m = s5.merge(redempt, on="household_key", how="left")
red_m["hit"] = (red_m.DAY >= red_m.alert_day) & (red_m.DAY <= red_m.window_end)
red_hit = red_m.groupby("household_key").hit.any().rename("redeemed_in_window")
s5 = s5.merge(red_hit, on="household_key", how="left")
s5["redeemed_in_window"] = s5.redeemed_in_window.fillna(False)

# 진완 연결: 홈스토어에서 선호상품이 전단/진열된 주가 윈도우 내 존재?
s5 = s5.merge(homestore, on="household_key", how="left")
s5["alert_week"] = ((s5.alert_day - 1) // 7 + 1).astype(int)
s5["end_week"] = ((s5.window_end - 1) // 7 + 1).astype(int)

pref_pairs = pref.merge(homestore, on="household_key")
pref_pairs = pref_pairs[pref_pairs.household_key.isin(s5.household_key)]
con2 = duckdb.connect(os.path.join(BASE, "data/processed/dunnhumby.duckdb"), read_only=True)
con2.register("pref_pairs", pref_pairs)
con2.register("s5w", s5[["household_key", "alert_week", "end_week"]])
promo_hit = con2.execute("""
    SELECT s.household_key, TRUE AS promo_in_window
    FROM s5w s
    JOIN pref_pairs pp ON pp.household_key = s.household_key
    JOIN causal_data c ON c.PRODUCT_ID = pp.PRODUCT_ID AND c.STORE_ID = pp.home_store
    WHERE c.WEEK_NO BETWEEN s.alert_week AND s.end_week
      AND (c.mailer <> '0' OR c.display NOT IN ('0', 'A'))
    GROUP BY 1
""").df()
s5 = s5.merge(promo_hit, on="household_key", how="left")
s5["promo_in_window"] = s5.promo_in_window.fillna(False)
s5.to_csv(os.path.join(OUT, "step5_exposure_raw.csv"), index=False)

def s5_summary(df):
    g = df.groupby("churned").agg(
        n=("household_key", "size"),
        캠페인수신=("campaign_in_window", "mean"),
        쿠폰사용=("redeemed_in_window", "mean"),
        선호상품프로모션노출=("promo_in_window", "mean"),
    ).reset_index()
    g["구분"] = g.churned.map({True: "이탈", False: "복귀"})
    return g[["구분", "n", "캠페인수신", "쿠폰사용", "선호상품프로모션노출"]]

s5_all = s5_summary(s5); s5_all["대상"] = "전체 경보"
s5_hv = s5_summary(s5[s5.high_value]); s5_hv["대상"] = "고가치 경보"
s5_out = pd.concat([s5_all, s5_hv])
s5_out.to_csv(os.path.join(OUT, "step5_exposure_summary.csv"), index=False)

# ---------- STEP 6: 조기 신호 (현재 점진형 가구) ----------
step6_rows = []
for hh in inc_set:
    if churn[hh] or not hv[hh]:
        continue
    days = vd[hh]
    gaps = np.diff(days)
    if len(gaps) < 3:
        continue
    recent3 = float(np.mean(gaps[-3:]))
    open_gap = DAY_W101_END - int(days[-1])
    m = med[hh]
    step6_rows.append({"household_key": hh, "median_gap": m, "recent3_mean_gap": recent3,
                       "open_gap": open_gap,
                       "widening": recent3 >= 1.5 * m})
s6 = pd.DataFrame(step6_rows)
s6.to_csv(os.path.join(OUT, "step6_early_signal.csv"), index=False)

# ---------- 퍼널 & 타임라인 예시 ----------
funnel = pd.DataFrame([
    {"stage": "1) 전체 가구 (W17~101 장보기)", "n": n_hh_all},
    {"stage": "2) baseline 충족 (W17~50 방문 8회+)", "n": len(included)},
    {"stage": "3) 경보 발생 (thr 2.0, W51~80)", "n": volume["total_first_alerts"]},
    {"stage": "4) 고가치 경보", "n": volume["hv_first_alerts"]},
    {"stage": "5) 실제 이탈 (고가치 경보∩이탈)", "n": scores[2.0]["고가치"]["TP"]},
])
funnel.to_csv(os.path.join(OUT, "viz_funnel.csv"), index=False)

# 대표 가구 타임라인: 정탐 고가치 2곳 + 오탐 1곳
ex_tp = fa_char[fa_char.churned & fa_char.high_value].nlargest(2, "n_episodes")
ex_fp = fa_char[~fa_char.churned & fa_char.high_value].nlargest(1, "n_episodes")
tl_rows = []
for _, r in pd.concat([ex_tp, ex_fp]).iterrows():
    hh = r.household_key
    for d in vd[hh]:
        tl_rows.append({"household_key": hh, "day": int(d), "type": "visit"})
    tl_rows.append({"household_key": hh, "day": int(r.first_alert), "type": "alert"})
    scan = vd[hh][vd[hh] <= DAY_W80_END]
    tl_rows.append({"household_key": hh, "day": int(scan[-1]) + 35, "type": "day35_rule"})
    for _, c in camp[camp.household_key == hh].iterrows():
        tl_rows.append({"household_key": hh, "day": int(c.START_DAY), "type": "campaign_start"})
pd.DataFrame(tl_rows).to_csv(os.path.join(OUT, "viz_timeline_examples.csv"), index=False)

# ---------- 결과 JSON 덤프 ----------
summary = {
    "n_hh_all": int(n_hh_all),
    "n_hh_with_baseline": int(n_hh_with_baseline),
    "n_excluded_no_baseline": int(n_excluded_no_baseline),
    "n_excluded_lowvisits": int(n_excluded_lowvisits),
    "n_included": int(len(included)),
    "n_high_value": int(included.high_value.sum()),
    "hv_spend_cut": float(cut),
    "gap_dist": gap_dist,
    "churn_rate_overall": float(included.churned.mean()),
    "churn_n": int(included.churned.sum()),
    "churn_rate_hv": float(included[included.high_value].churned.mean()),
    "churn_n_hv": int(included[included.high_value].churned.sum()),
    "volume_thr2": volume,
    "scores": {str(t): scores[t] for t in THRESHOLDS},
    "lead_overall": {
        "n": int(len(lead)),
        "median": float(lead.lead_days.median()),
        "p25": float(lead.lead_days.quantile(0.25)),
        "p75": float(lead.lead_days.quantile(0.75)),
        "rule_earlier_share": float((lead.lead_days > 0).mean()),
        "rule_in_window_share": float(lead.rule_in_window.mean()),
        "day35_in_window_share": float(lead.day35_in_window.mean()),
    },
    "lead_by_group": lead_summary.to_dict("records"),
    "step5": s5_out.to_dict("records"),
    "step5_n_returned_after_alert": int(s5.returned_after_alert.sum()),
    "step6": {
        "n_hv_normal": int(len(s6)),
        "n_widening": int(s6.widening.sum()),
        "share_widening": float(s6.widening.mean()) if len(s6) else None,
    },
    "fp_profile": fp_profile.to_dict("records"),
}
included.to_csv(os.path.join(OUT, "step1_baseline.csv"), index=False)
with open(os.path.join(OUT, "summary.json"), "w") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
