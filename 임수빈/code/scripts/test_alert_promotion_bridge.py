from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
REPORT = ROOT / "reports" / "alert_promotion_bridge_validation.md"
PRIORITY = ["BACON", "LUNCHMEAT", "DINNER SAUSAGE"]
RANDOM_SEED = 42


def smd(x, y):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    pooled = np.sqrt((np.nanvar(x, ddof=1) + np.nanvar(y, ddof=1)) / 2)
    return 0.0 if not np.isfinite(pooled) or pooled == 0 else (np.nanmean(x) - np.nanmean(y)) / pooled


def paired_inference(diff, n_boot=5000, n_perm=20000):
    values = np.asarray(diff, float)
    values = values[np.isfinite(values)]
    if len(values) < 2:
        return dict(n_pairs=len(values), effect=np.nan, ci_low=np.nan, ci_high=np.nan, p_two_sided=np.nan)
    rng = np.random.default_rng(RANDOM_SEED)
    boots = rng.choice(values, size=(n_boot, len(values)), replace=True).mean(axis=1)
    observed = abs(values.mean())
    extreme = 0
    done = 0
    while done < n_perm:
        batch = min(500, n_perm - done)
        perm = (rng.choice([-1, 1], size=(batch, len(values))) * values).mean(axis=1)
        extreme += (np.abs(perm) >= observed).sum()
        done += batch
    return dict(
        n_pairs=len(values),
        effect=values.mean(),
        ci_low=np.quantile(boots, 0.025),
        ci_high=np.quantile(boots, 0.975),
        p_two_sided=(extreme + 1) / (n_perm + 1),
    )


def build_alerts(tx):
    base = tx.loc[tx["WEEK_NO"].between(17, 50)].copy()
    active_weeks = base.groupby("household_key")["WEEK_NO"].nunique()
    eligible = active_weeks.loc[active_weeks >= 8].index
    value = base.loc[base["household_key"].isin(eligible)].groupby("household_key")["SALES_VALUE"].sum()
    cutoff = value.quantile(0.8)
    high_value = set(value.loc[value >= cutoff].index)

    purchase_days = base[["household_key", "DAY"]].drop_duplicates().sort_values(["household_key", "DAY"])
    purchase_days["gap"] = purchase_days.groupby("household_key")["DAY"].diff()
    median_gap = purchase_days.groupby("household_key")["gap"].median()

    diversity_windows = []
    for week in range(24, 51):
        diversity_windows.append(
            base.loc[base["WEEK_NO"].between(week - 7, week)]
            .groupby("household_key")["COMMODITY_DESC"]
            .nunique()
            .rename(week)
        )
    usual_diversity = pd.concat(diversity_windows, axis=1).median(axis=1)

    alert_rows = []
    for week in range(51, 81):
        end_day = int(tx.loc[tx["WEEK_NO"].eq(week), "DAY"].max())
        last_day = tx.loc[tx["DAY"].le(end_day)].groupby("household_key")["DAY"].max()
        gap_ratio = (end_day - last_day) / median_gap
        recent_diversity = (
            tx.loc[tx["WEEK_NO"].between(week - 7, week)]
            .groupby("household_key")["COMMODITY_DESC"]
            .nunique()
        )
        diversity_ratio = recent_diversity / usual_diversity
        alerted = set(gap_ratio.loc[(gap_ratio >= 1.5) & (diversity_ratio < 0.7)].index) & high_value
        alert_rows.extend(
            {
                "household_key": household,
                "alert_week": week,
                "gap_ratio": gap_ratio.loc[household],
                "diversity_ratio": diversity_ratio.loc[household],
            }
            for household in alerted
        )
    alerts = pd.DataFrame(alert_rows).sort_values(["household_key", "alert_week"]).drop_duplicates("household_key")
    return base, alerts, cutoff


def build_candidates(base, alerts):
    home_store = (
        base.groupby(["household_key", "STORE_ID"])["BASKET_ID"]
        .nunique()
        .reset_index(name="home_baskets")
        .sort_values(["household_key", "home_baskets", "STORE_ID"], ascending=[True, False, True])
        .drop_duplicates("household_key")
        .rename(columns={"STORE_ID": "home_store"})
    )
    preferred_products = (
        base.loc[base["COMMODITY_DESC"].isin(PRIORITY)]
        .groupby(["household_key", "COMMODITY_DESC", "PRODUCT_ID"])
        .agg(product_revenue=("SALES_VALUE", "sum"), product_baskets=("BASKET_ID", "nunique"))
        .reset_index()
    )
    preferred_categories = (
        preferred_products.groupby(["household_key", "COMMODITY_DESC"])
        .agg(category_revenue=("product_revenue", "sum"), category_baskets=("product_baskets", "sum"))
        .reset_index()
        .query("category_baskets >= 2")
        .sort_values(["household_key", "category_revenue", "COMMODITY_DESC"], ascending=[True, False, True])
        .drop_duplicates("household_key")
    )
    baseline_total = base.groupby("household_key")["SALES_VALUE"].sum().rename("baseline_revenue")
    candidates = (
        alerts.merge(home_store[["household_key", "home_store"]], on="household_key", how="inner")
        .merge(preferred_categories, on="household_key", how="inner")
        .merge(baseline_total, on="household_key", how="left")
    )
    candidates["baseline_weekly_revenue"] = candidates["baseline_revenue"] / 34
    candidates["baseline_category_share"] = candidates["category_revenue"] / candidates["baseline_revenue"]
    preferred_products = preferred_products.merge(
        candidates[["household_key", "COMMODITY_DESC", "home_store", "alert_week"]],
        on=["household_key", "COMMODITY_DESC"],
        how="inner",
    )
    return candidates, preferred_products


def load_relevant_promotions(preferred_products):
    products = set(preferred_products["PRODUCT_ID"].astype(int))
    stores = set(preferred_products["home_store"].astype(int))
    parts = []
    dtype = {"PRODUCT_ID": "int32", "STORE_ID": "int32", "WEEK_NO": "int16", "display": "string", "mailer": "string"}
    for chunk in pd.read_csv(ROOT / "causal_data.csv", chunksize=2_000_000, dtype=dtype):
        keep = chunk["PRODUCT_ID"].isin(products) & chunk["STORE_ID"].isin(stores) & chunk["WEEK_NO"].between(51, 82)
        if keep.any():
            parts.append(chunk.loc[keep].copy())
    return pd.concat(parts, ignore_index=True)


def classify_exposure(preferred_products, promotions, window_weeks=0, display_a_is_active=True):
    expanded = []
    for offset in range(window_weeks + 1):
        part = preferred_products.copy()
        part["exposure_week"] = part["alert_week"] + offset
        expanded.append(part)
    lookup = pd.concat(expanded, ignore_index=True).merge(
        promotions,
        left_on=["PRODUCT_ID", "home_store", "exposure_week"],
        right_on=["PRODUCT_ID", "STORE_ID", "WEEK_NO"],
        how="inner",
    )
    if lookup.empty:
        return pd.DataFrame()
    lookup["week_offset"] = lookup["exposure_week"] - lookup["alert_week"]
    first_week = lookup.groupby("household_key")["week_offset"].transform("min")
    lookup = lookup.loc[lookup["week_offset"].eq(first_week)].copy()
    display = lookup["display"].fillna("0").ne("0")
    if not display_a_is_active:
        display &= lookup["display"].ne("A")
    mailer = lookup["mailer"].fillna("0").ne("0")
    lookup["promo_group"] = np.select(
        [display & mailer, display, mailer], ["combo", "display_only", "mailer_only"], default="none"
    )
    lookup["weight"] = lookup["product_revenue"].clip(lower=0)
    lookup["weight"] = lookup["weight"].where(lookup["weight"].gt(0), 1.0)
    shares = (
        lookup.pivot_table(index="household_key", columns="promo_group", values="weight", aggfunc="sum", fill_value=0)
        .reindex(columns=["combo", "display_only", "mailer_only", "none"], fill_value=0)
    )
    shares = shares.div(shares.sum(axis=1), axis=0).add_suffix("_share").reset_index()
    exposure_week = lookup.groupby("household_key")["exposure_week"].min().rename("exposure_week")
    shares = shares.merge(exposure_week, on="household_key")
    single_max = shares[["display_only_share", "mailer_only_share"]].max(axis=1)
    shares["exposure_group"] = np.where(
        shares["combo_share"] > single_max,
        "combo",
        np.where(single_max > shares["combo_share"], "single", "ambiguous"),
    )
    return shares


def add_outcomes(cohort, tx):
    rows = []
    for row in cohort.itertuples(index=False):
        pre = tx.loc[
            tx["household_key"].eq(row.household_key)
            & tx["WEEK_NO"].between(row.exposure_week - 8, row.exposure_week - 1)
        ]
        post = tx.loc[
            tx["household_key"].eq(row.household_key)
            & tx["WEEK_NO"].between(row.exposure_week + 1, row.exposure_week + 8)
        ]
        category_post = post.loc[post["COMMODITY_DESC"].eq(row.COMMODITY_DESC)]
        pre_revenue = pre["SALES_VALUE"].sum()
        post_revenue = post["SALES_VALUE"].sum()
        rows.append(
            {
                "household_key": row.household_key,
                "pre8_weekly_revenue": pre_revenue / 8,
                "post8_weekly_revenue": post_revenue / 8,
                "revenue_retention_pct": 100 * (post_revenue / 8) / row.baseline_weekly_revenue,
                "weekly_revenue_change": (post_revenue - pre_revenue) / 8,
                "post8_category_revenue": category_post["SALES_VALUE"].sum(),
                "post8_category_purchase": int(category_post["BASKET_ID"].nunique() > 0),
                "post8_active_weeks": post["WEEK_NO"].nunique(),
            }
        )
    return cohort.merge(pd.DataFrame(rows), on="household_key", how="left")


def match_and_test(cohort, label):
    combo = cohort.loc[cohort["exposure_group"].eq("combo")].copy()
    single = cohort.loc[cohort["exposure_group"].eq("single")].copy()
    covariates = [
        "baseline_weekly_revenue",
        "pre8_weekly_revenue",
        "baseline_category_share",
        "gap_ratio",
        "diversity_ratio",
        "exposure_week",
    ]
    pairs = []
    for category, treated_group in combo.groupby("COMMODITY_DESC"):
        controls = single.loc[single["COMMODITY_DESC"].eq(category)].copy()
        if controls.empty:
            continue
        combined = pd.concat([treated_group[covariates], controls[covariates]])
        scale = combined.std(ddof=0).replace(0, 1).fillna(1)
        center = combined.mean()
        treated_z = ((treated_group[covariates] - center) / scale).to_numpy(float)
        control_z = ((controls[covariates] - center) / scale).to_numpy(float)
        distance = ((treated_z[:, None, :] - control_z[None, :, :]) ** 2).sum(axis=2)
        treated_idx, control_idx = linear_sum_assignment(distance)
        for ti, ci in zip(treated_idx, control_idx):
            pairs.append(
                (
                    int(treated_group.iloc[ti]["household_key"]),
                    int(controls.iloc[ci]["household_key"]),
                    category,
                    float(distance[ti, ci]),
                )
            )
    pair_table = pd.DataFrame(pairs, columns=["treated_household", "control_household", "COMMODITY_DESC", "distance"])
    if pair_table.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    treated = pair_table.merge(cohort, left_on="treated_household", right_on="household_key", how="left")
    controls = pair_table.merge(cohort, left_on="control_household", right_on="household_key", how="left")
    balance = []
    for column in covariates:
        balance.append({"analysis": label, "covariate": column, "smd": smd(treated[column], controls[column])})
    outcomes = [
        "revenue_retention_pct",
        "weekly_revenue_change",
        "post8_category_revenue",
        "post8_category_purchase",
        "post8_active_weeks",
    ]
    tests = []
    for outcome in outcomes:
        result = paired_inference(treated[outcome].to_numpy() - controls[outcome].to_numpy())
        tests.append(
            {
                "analysis": label,
                "outcome": outcome,
                "combo_mean": treated[outcome].mean(),
                "single_mean": controls[outcome].mean(),
                **result,
                "unique_controls": controls["household_key"].nunique(),
            }
        )
    pair_table["analysis"] = label
    return pair_table, pd.DataFrame(balance), pd.DataFrame(tests)


def main():
    tx = pd.read_csv(
        ROOT / "transaction_data.csv",
        usecols=["household_key", "BASKET_ID", "DAY", "PRODUCT_ID", "SALES_VALUE", "STORE_ID", "WEEK_NO"],
    )
    products = pd.read_csv(ROOT / "product.csv", usecols=["PRODUCT_ID", "DEPARTMENT", "COMMODITY_DESC"])
    tx = tx.merge(products, on="PRODUCT_ID", how="left", validate="many_to_one")
    tx = tx.loc[
        tx["WEEK_NO"].between(17, 101)
        & ~tx["DEPARTMENT"].isin(["KIOSK-GAS", "MISC SALES TRAN", "MISC. TRANS."])
    ].copy()
    base, alerts, value_cutoff = build_alerts(tx)
    candidates, preferred_products = build_candidates(base, alerts)
    promotions = load_relevant_promotions(preferred_products)

    cohorts = []
    all_pairs = []
    all_balance = []
    all_tests = []
    settings = [(0, True), (1, True), (2, True), (2, False)]
    for window, a_active in settings:
        label = f"window_0_{window}_displayA_{'active' if a_active else 'inactive'}"
        exposure = classify_exposure(preferred_products, promotions, window, a_active)
        cohort = candidates.merge(exposure, on="household_key", how="inner")
        cohort = cohort.loc[cohort["exposure_group"].ne("ambiguous")].copy()
        cohort = add_outcomes(cohort, tx)
        cohort["analysis"] = label
        cohorts.append(cohort)
        pairs, balance, tests = match_and_test(cohort, label)
        all_pairs.append(pairs)
        all_balance.append(balance)
        all_tests.append(tests)

    cohort_output = pd.concat(cohorts, ignore_index=True)
    pair_output = pd.concat(all_pairs, ignore_index=True)
    balance_output = pd.concat(all_balance, ignore_index=True)
    test_output = pd.concat(all_tests, ignore_index=True)
    cohort_output.to_csv(DATA / "alert_promotion_bridge_cohort.csv", index=False, encoding="utf-8-sig")
    pair_output.to_csv(DATA / "alert_promotion_bridge_pairs.csv", index=False, encoding="utf-8-sig")
    balance_output.to_csv(DATA / "alert_promotion_bridge_balance.csv", index=False, encoding="utf-8-sig")
    test_output.to_csv(DATA / "alert_promotion_bridge_effects.csv", index=False, encoding="utf-8-sig")

    primary_label = "window_0_2_displayA_active"
    primary_cohort = cohort_output.loc[cohort_output["analysis"].eq(primary_label)]
    primary_tests = test_output.loc[test_output["analysis"].eq(primary_label)]
    retention = primary_tests.loc[primary_tests["outcome"].eq("revenue_retention_pct")].iloc[0]
    category = primary_tests.loc[primary_tests["outcome"].eq("post8_category_revenue")].iloc[0]
    max_balance = balance_output.loc[balance_output["analysis"].eq(primary_label), "smd"].abs().max()
    sensitivity = test_output.loc[test_output["outcome"].eq("revenue_retention_pct")]
    consistent = ((sensitivity["ci_low"] > 0).all() or (sensitivity["ci_high"] < 0).all())
    decision = (
        "결합 노출의 지출 방어 효과를 지지한다."
        if retention["ci_low"] > 0 and retention["p_two_sided"] < 0.05 and consistent
        else "현재 표본으로 결합 노출의 지출 방어 효과를 지지할 충분한 근거가 없다."
    )
    lines = [
        "# 지출 감소 경보 고객 × 선호 카테고리 결합 프로모션 백테스트",
        "",
        "## 결론",
        "",
        f"> {decision}",
        "",
        "탐지 규칙과 카테고리 프로모션 효과를 각각 확인했던 기존 분석을 실제 고객-시점-홈스토어-상품 수준에서 연결했다.",
        "",
        "## 분석 설계",
        "",
        f"- 기준기간: W17-W50, 활동주차 8주 이상, 지출 상위 20% (컷 {value_cutoff:,.2f})",
        "- 첫 경보: W51-W80 중 개인 방문 간격 1.5배 이상 및 최근 8주 카테고리 다양성 70% 미만",
        "- 선호 카테고리: BACON, LUNCHMEAT, DINNER SAUSAGE 중 기준기간 2개 이상 장바구니에서 구매하고 매출이 가장 큰 카테고리",
        "- 노출: 경보 주부터 2주 이내 홈스토어에서 과거 구매 상품에 기록된 첫 프로모션",
        "- 처리군: 구매이력 가중 결합 노출 비중이 각 단독 노출 비중보다 큰 고객",
        "- 비교군: 진열만 또는 전단만 노출 비중이 결합 노출보다 큰 고객",
        "- 매칭: 동일 카테고리 안에서 기준 매출, 직전 8주 매출, 카테고리 비중, 두 경보 신호, 노출 주차가 가장 가까운 고객",
        "- 결과: 노출 다음 8주의 평소 대비 지출 유지율, 매출 변화, 대상 카테고리 매출·구매, 활동주차",
        "",
        "## 표본과 매칭",
        "",
        f"- 경보 고객: {alerts['household_key'].nunique():,}명",
        f"- 우선 카테고리 반복구매 교집합: {candidates['household_key'].nunique():,}명",
        f"- 주 분석 노출 확인·분류 고객: {primary_cohort['household_key'].nunique():,}명",
        f"- 결합 우세: {(primary_cohort['exposure_group']=='combo').sum():,}명, 단독 우세: {(primary_cohort['exposure_group']=='single').sum():,}명",
        f"- 매칭 후 최대 절대 SMD: {max_balance:.3f}",
        "",
        "## 주 분석 결과",
        "",
        f"- 8주 지출 유지율: 결합 {retention['combo_mean']:.1f}%, 단독 {retention['single_mean']:.1f}%, 차이 {retention['effect']:+.1f}%p",
        f"- 95% bootstrap CI: [{retention['ci_low']:.1f}, {retention['ci_high']:.1f}], 양측 부호순열 p={retention['p_two_sided']:.4f}",
        f"- 대상 카테고리 8주 매출 차이: {category['effect']:+.2f} (95% CI [{category['ci_low']:.2f}, {category['ci_high']:.2f}])",
        "",
        "## 민감도",
        "",
        "| 설정 | 매칭쌍 | 지출 유지율 차이(%p) | 95% CI | p-value |",
        "| --- | ---: | ---: | --- | ---: |",
    ]
    for row in sensitivity.itertuples(index=False):
        lines.append(f"| {row.analysis} | {row.n_pairs} | {row.effect:+.1f} | [{row.ci_low:.1f}, {row.ci_high:.1f}] | {row.p_two_sided:.4f} |")
    lines += [
        "",
        "## 해석 제한",
        "",
        "- 프로모션은 무작위 배정되지 않았으므로 매칭 후에도 관측되지 않은 차이가 남을 수 있다.",
        "- causal_data의 기록은 홈스토어에서의 프로모션 가용성이지 고객이 실제로 전단·진열을 봤다는 증거는 아니다.",
        "- 한 고객의 과거 구매 상품 중 관측된 프로모션에 구매이력 가중치를 적용했으며, 상품별 노출 커버리지가 완전하지 않다.",
        "- 따라서 유의한 결과도 확정적 인과효과가 아니라 A/B 테스트 진행 여부를 판단하는 백테스트 근거로 해석한다.",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:35]))
    print(f"\n결과 저장: {REPORT}")


if __name__ == "__main__":
    main()
