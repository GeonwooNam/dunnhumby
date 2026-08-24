from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
import statsmodels.formula.api as smf


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
SOURCE = DATA / "leading_category_contraction_customer_categories.csv"
REPORT = ROOT / "reports" / "soft_drinks_targeted_promotion_validation.md"
CATEGORY = "SOFT DRINKS"
ORIGINS = [50, 58, 66, 74, 82, 90]
RANDOM_SEED = 42


def smd(x, y):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    pooled = np.sqrt((np.nanvar(x, ddof=1) + np.nanvar(y, ddof=1)) / 2)
    return 0.0 if not np.isfinite(pooled) or pooled == 0 else (np.nanmean(x) - np.nanmean(y)) / pooled


def paired_inference(diff, cluster_ids, n_boot=5000, n_perm=20000):
    frame = pd.DataFrame({"diff": np.asarray(diff, float), "cluster": cluster_ids}).dropna()
    if len(frame) < 2:
        return dict(n_pairs=len(frame), effect=np.nan, ci_low=np.nan, ci_high=np.nan, p_two_sided=np.nan)
    clusters = frame["cluster"].unique()
    grouped = {cluster: frame.loc[frame["cluster"].eq(cluster), "diff"].to_numpy() for cluster in clusters}
    rng = np.random.default_rng(RANDOM_SEED)
    boot = []
    for _ in range(n_boot):
        sample = rng.choice(clusters, size=len(clusters), replace=True)
        boot.append(np.concatenate([grouped[c] for c in sample]).mean())
    values = frame["diff"].to_numpy()
    observed = abs(values.mean())
    extreme = 0
    done = 0
    while done < n_perm:
        batch = min(500, n_perm - done)
        signs = rng.choice([-1, 1], size=(batch, len(clusters)))
        perm = np.empty(batch)
        for i in range(batch):
            signed = np.concatenate([grouped[c] * signs[i, j] for j, c in enumerate(clusters)])
            perm[i] = signed.mean()
        extreme += (np.abs(perm) >= observed).sum()
        done += batch
    return {
        "n_pairs": len(frame),
        "effect": values.mean(),
        "ci_low": np.quantile(boot, 0.025),
        "ci_high": np.quantile(boot, 0.975),
        "p_two_sided": (extreme + 1) / (n_perm + 1),
    }


def build_candidates(tx, source):
    rows = []
    product_rows = []
    for origin in ORIGINS:
        ids = source.loc[source["origin_week"].eq(origin), "household_key"].unique()
        baseline = tx.loc[tx["WEEK_NO"].between(origin - 33, origin - 8) & tx["household_key"].isin(ids)]
        recent = tx.loc[tx["WEEK_NO"].between(origin - 7, origin) & tx["household_key"].isin(ids)]
        home = (
            baseline.groupby(["household_key", "STORE_ID"])["BASKET_ID"]
            .nunique().reset_index(name="home_baskets")
            .sort_values(["household_key", "home_baskets", "STORE_ID"], ascending=[True, False, True])
            .drop_duplicates("household_key")
            .rename(columns={"STORE_ID": "home_store"})
        )
        base_total = baseline.groupby("household_key").agg(
            baseline_revenue=("SALES_VALUE", "sum"), baseline_baskets=("BASKET_ID", "nunique")
        )
        recent_total = recent.groupby("household_key").agg(
            recent_revenue=("SALES_VALUE", "sum"), recent_baskets=("BASKET_ID", "nunique")
        )
        soft = baseline.loc[baseline["COMMODITY_DESC"].eq(CATEGORY)]
        soft_products = soft.groupby(["household_key", "PRODUCT_ID"]).agg(
            product_revenue=("SALES_VALUE", "sum"), product_baskets=("BASKET_ID", "nunique")
        ).reset_index()
        cohort = source.loc[source["origin_week"].eq(origin)].merge(home, on="household_key", how="inner")
        cohort = cohort.merge(base_total, on="household_key", how="left").merge(recent_total, on="household_key", how="left")
        cohort[["recent_revenue", "recent_baskets"]] = cohort[["recent_revenue", "recent_baskets"]].fillna(0)
        cohort["baseline_weekly_revenue_rebuilt"] = cohort["baseline_revenue"] / 26
        cohort["recent_weekly_revenue"] = cohort["recent_revenue"] / 8
        cohort["recent_total_revenue_ratio"] = (
            cohort["recent_weekly_revenue"] / cohort["baseline_weekly_revenue_rebuilt"]
        )
        cohort["baseline_soft_revenue_share"] = cohort["baseline_category_revenue"] / cohort["baseline_revenue"]
        rows.append(cohort)
        product_rows.append(
            soft_products.merge(
                cohort[["household_key", "origin_week", "home_store"]], on="household_key", how="inner"
            )
        )
    return pd.concat(rows, ignore_index=True), pd.concat(product_rows, ignore_index=True)


def load_promotions(products):
    product_ids = set(products["PRODUCT_ID"].astype(int))
    stores = set(products["home_store"].astype(int))
    parts = []
    dtype = {"PRODUCT_ID": "int32", "STORE_ID": "int32", "WEEK_NO": "int16", "display": "string", "mailer": "string"}
    for chunk in pd.read_csv(ROOT / "causal_data.csv", chunksize=2_000_000, dtype=dtype):
        keep = chunk["PRODUCT_ID"].isin(product_ids) & chunk["STORE_ID"].isin(stores) & chunk["WEEK_NO"].between(50, 92)
        if keep.any():
            parts.append(chunk.loc[keep].copy())
    return pd.concat(parts, ignore_index=True)


def classify_exposure(products, promotions, window, display_a_active=True):
    expanded = []
    for offset in range(window + 1):
        part = products.copy()
        part["exposure_week"] = part["origin_week"] + offset
        expanded.append(part)
    joined = pd.concat(expanded, ignore_index=True).merge(
        promotions,
        left_on=["PRODUCT_ID", "home_store", "exposure_week"],
        right_on=["PRODUCT_ID", "STORE_ID", "WEEK_NO"],
        how="inner",
    )
    if joined.empty:
        return pd.DataFrame()
    joined["offset"] = joined["exposure_week"] - joined["origin_week"]
    first = joined.groupby(["household_key", "origin_week"])["offset"].transform("min")
    joined = joined.loc[joined["offset"].eq(first)].copy()
    display = joined["display"].fillna("0").ne("0")
    if not display_a_active:
        display &= joined["display"].ne("A")
    mailer = joined["mailer"].fillna("0").ne("0")
    joined["promo_group"] = np.select(
        [display & mailer, display, mailer], ["combo", "display_only", "mailer_only"], default="none"
    )
    joined["weight"] = joined["product_revenue"].clip(lower=0).replace(0, 1)
    shares = joined.pivot_table(
        index=["household_key", "origin_week"], columns="promo_group", values="weight", aggfunc="sum", fill_value=0
    ).reindex(columns=["combo", "display_only", "mailer_only", "none"], fill_value=0)
    shares = shares.div(shares.sum(axis=1), axis=0).add_suffix("_share").reset_index()
    exposure_week = joined.groupby(["household_key", "origin_week"])["exposure_week"].min().rename("exposure_week")
    shares = shares.merge(exposure_week, on=["household_key", "origin_week"])
    single = shares[["display_only_share", "mailer_only_share"]].max(axis=1)
    shares["exposure_group"] = np.where(
        shares["combo_share"] > single, "combo", np.where(single > shares["combo_share"], "single", "ambiguous")
    )
    return shares


def add_outcomes(cohort, tx):
    rows = []
    for row in cohort.itertuples(index=False):
        post = tx.loc[
            tx["household_key"].eq(row.household_key)
            & tx["WEEK_NO"].between(row.exposure_week + 1, row.exposure_week + 8)
        ]
        soft = post.loc[post["COMMODITY_DESC"].eq(CATEGORY)]
        post_revenue = post["SALES_VALUE"].sum()
        rows.append(
            {
                "household_key": row.household_key,
                "origin_week": row.origin_week,
                "post8_revenue": post_revenue,
                "post8_weekly_revenue": post_revenue / 8,
                "post8_revenue_retention_pct": 100 * (post_revenue / 8) / row.baseline_weekly_revenue_rebuilt,
                "post8_baskets": post["BASKET_ID"].nunique(),
                "post8_active_weeks": post["WEEK_NO"].nunique(),
                "post8_soft_revenue": soft["SALES_VALUE"].sum(),
                "post8_soft_baskets": soft["BASKET_ID"].nunique(),
                "post8_soft_repurchase": int(soft["BASKET_ID"].nunique() > 0),
            }
        )
    return cohort.merge(pd.DataFrame(rows), on=["household_key", "origin_week"], how="left")


def match_and_test(cohort, label):
    treated = cohort.loc[cohort["exposure_group"].eq("combo")].copy()
    controls = cohort.loc[cohort["exposure_group"].eq("single")].copy()
    covariates = [
        "baseline_weekly_revenue_rebuilt", "recent_total_revenue_ratio", "baseline_soft_revenue_share",
        "category_basket_pace_ratio", "baseline_category_baskets", "diversity_ratio", "exposure_week",
    ]
    if treated.empty or controls.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    pair_parts = []
    for origin, treated_period in treated.groupby("origin_week"):
        control_period = controls.loc[controls["origin_week"].eq(origin)]
        if control_period.empty:
            continue
        combined = pd.concat([treated_period[covariates], control_period[covariates]])
        center = combined.mean()
        scale = combined.std(ddof=0).replace(0, 1).fillna(1)
        tz = ((treated_period[covariates] - center) / scale).fillna(0).to_numpy(float)
        cz = ((control_period[covariates] - center) / scale).fillna(0).to_numpy(float)
        distance = ((tz[:, None, :] - cz[None, :, :]) ** 2).sum(axis=2)
        ti, ci = linear_sum_assignment(distance)
        pair_parts.append(
            pd.DataFrame(
                {
                    "treated_index": treated_period.index.to_numpy()[ti],
                    "control_index": control_period.index.to_numpy()[ci],
                    "distance": distance[ti, ci],
                    "analysis": label,
                }
            )
        )
    if not pair_parts:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    pairs = pd.concat(pair_parts, ignore_index=True)
    t = cohort.loc[pairs["treated_index"]].reset_index(drop=True)
    c = cohort.loc[pairs["control_index"]].reset_index(drop=True)
    balance = pd.DataFrame(
        [{"analysis": label, "covariate": column, "smd": smd(t[column], c[column])} for column in covariates]
    )
    outcomes = [
        "post8_soft_repurchase", "post8_soft_revenue", "post8_revenue_retention_pct",
        "post8_baskets", "post8_active_weeks",
    ]
    tests = []
    cluster_ids = t["household_key"].to_numpy()
    for outcome in outcomes:
        inference = paired_inference(t[outcome].to_numpy() - c[outcome].to_numpy(), cluster_ids)
        tests.append(
            {
                "analysis": label,
                "outcome": outcome,
                "combo_mean": t[outcome].mean(),
                "single_mean": c[outcome].mean(),
                **inference,
            }
        )
    pretrend = paired_inference(
        t["recent_total_revenue_ratio"].to_numpy() - c["recent_total_revenue_ratio"].to_numpy(), cluster_ids
    )
    tests.append(
        {
            "analysis": label,
            "outcome": "placebo_recent_total_revenue_ratio",
            "combo_mean": t["recent_total_revenue_ratio"].mean(),
            "single_mean": c["recent_total_revenue_ratio"].mean(),
            **pretrend,
        }
    )
    pairs["treated_household"] = t["household_key"].to_numpy()
    pairs["treated_origin"] = t["origin_week"].to_numpy()
    pairs["control_household"] = c["household_key"].to_numpy()
    pairs["control_origin"] = c["origin_week"].to_numpy()
    return pairs, balance, pd.DataFrame(tests)


def adjusted_regression(cohort, label):
    data = cohort.copy()
    data["combo_treatment"] = data["exposure_group"].eq("combo").astype(int)
    covariates = [
        "baseline_weekly_revenue_rebuilt", "recent_total_revenue_ratio", "baseline_soft_revenue_share",
        "category_basket_pace_ratio", "baseline_category_baskets", "diversity_ratio",
    ]
    standardized = []
    for column in covariates:
        name = f"{column}_z"
        scale = data[column].std()
        data[name] = (data[column] - data[column].mean()) / (scale if scale else 1)
        standardized.append(name)
    rhs = "combo_treatment + " + " + ".join(standardized) + " + C(origin_week)"
    rows = []
    for outcome in ["post8_soft_repurchase", "post8_soft_revenue", "post8_revenue_retention_pct"]:
        model = smf.ols(f"{outcome} ~ {rhs}", data=data).fit(
            cov_type="cluster", cov_kwds={"groups": data["household_key"]}
        )
        ci = model.conf_int().loc["combo_treatment"]
        rows.append(
            {
                "analysis": label,
                "outcome": outcome,
                "adjusted_effect": model.params["combo_treatment"],
                "ci_low": ci.iloc[0],
                "ci_high": ci.iloc[1],
                "p_value": model.pvalues["combo_treatment"],
                "n": int(model.nobs),
            }
        )
    return pd.DataFrame(rows)


def main():
    source = pd.read_csv(SOURCE)
    source = source.loc[source["COMMODITY_DESC"].eq(CATEGORY) & source["category_contracted"]].copy()
    tx = pd.read_csv(
        ROOT / "transaction_data.csv",
        usecols=["household_key", "BASKET_ID", "PRODUCT_ID", "SALES_VALUE", "STORE_ID", "WEEK_NO"],
    )
    product = pd.read_csv(ROOT / "product.csv", usecols=["PRODUCT_ID", "DEPARTMENT", "COMMODITY_DESC"])
    tx = tx.merge(product, on="PRODUCT_ID", how="left", validate="many_to_one")
    tx = tx.loc[
        tx["WEEK_NO"].between(17, 101)
        & ~tx["DEPARTMENT"].isin(["KIOSK-GAS", "MISC SALES TRAN", "MISC. TRANS."])
    ].copy()
    candidates, preferred_products = build_candidates(tx, source)
    promotions = load_promotions(preferred_products)

    cohorts, pairs_all, balances, tests_all, regressions = [], [], [], [], []
    for window, display_a in [(0, True), (1, True), (2, True), (2, False)]:
        label = f"window_0_{window}_displayA_{'active' if display_a else 'inactive'}"
        exposure = classify_exposure(preferred_products, promotions, window, display_a)
        cohort = candidates.merge(exposure, on=["household_key", "origin_week"], how="inner")
        cohort = cohort.loc[cohort["exposure_group"].ne("ambiguous")].copy()
        cohort = add_outcomes(cohort, tx)
        cohort["analysis"] = label
        pairs, balance, tests = match_and_test(cohort, label)
        cohorts.append(cohort)
        pairs_all.append(pairs)
        balances.append(balance)
        tests_all.append(tests)
        regressions.append(adjusted_regression(cohort, label))

    cohort_output = pd.concat(cohorts, ignore_index=True)
    pair_output = pd.concat(pairs_all, ignore_index=True)
    balance_output = pd.concat(balances, ignore_index=True)
    test_output = pd.concat(tests_all, ignore_index=True)
    regression_output = pd.concat(regressions, ignore_index=True)
    cohort_output.to_csv(DATA / "soft_drinks_targeted_promotion_cohort.csv", index=False, encoding="utf-8-sig")
    pair_output.to_csv(DATA / "soft_drinks_targeted_promotion_pairs.csv", index=False, encoding="utf-8-sig")
    balance_output.to_csv(DATA / "soft_drinks_targeted_promotion_balance.csv", index=False, encoding="utf-8-sig")
    test_output.to_csv(DATA / "soft_drinks_targeted_promotion_effects.csv", index=False, encoding="utf-8-sig")
    regression_output.to_csv(DATA / "soft_drinks_targeted_promotion_adjusted_effects.csv", index=False, encoding="utf-8-sig")

    primary = "window_0_2_displayA_active"
    cohort = cohort_output.loc[cohort_output["analysis"].eq(primary)]
    effects = test_output.loc[test_output["analysis"].eq(primary)]
    repurchase = effects.loc[effects["outcome"].eq("post8_soft_repurchase")].iloc[0]
    soft_revenue = effects.loc[effects["outcome"].eq("post8_soft_revenue")].iloc[0]
    total_retention = effects.loc[effects["outcome"].eq("post8_revenue_retention_pct")].iloc[0]
    placebo = effects.loc[effects["outcome"].eq("placebo_recent_total_revenue_ratio")].iloc[0]
    adjusted = regression_output.loc[regression_output["analysis"].eq(primary)]
    adjusted_repurchase = adjusted.loc[adjusted["outcome"].eq("post8_soft_repurchase")].iloc[0]
    adjusted_soft_revenue = adjusted.loc[adjusted["outcome"].eq("post8_soft_revenue")].iloc[0]
    adjusted_total = adjusted.loc[adjusted["outcome"].eq("post8_revenue_retention_pct")].iloc[0]
    max_smd = balance_output.loc[balance_output["analysis"].eq(primary), "smd"].abs().max()
    sensitivity = test_output.loc[test_output["outcome"].eq("post8_soft_repurchase")]
    supported = (
        repurchase["ci_low"] > 0
        and total_retention["ci_low"] >= 0
        and (sensitivity["effect"] > 0).all()
        and abs(placebo["effect"]) < 0.10
    )
    decision = (
        "SOFT DRINKS 축소 고객 대상 결합 프로모션 파일럿을 지지한다."
        if supported
        else "현재 관찰자료로 SOFT DRINKS 축소 고객 대상 결합 프로모션의 우월성을 지지할 충분한 근거가 없다."
    )
    lines = [
        "# SOFT DRINKS 축소 고객 대상 결합 프로모션 표적 백테스트",
        "",
        "## 판정",
        "",
        f"> {decision}",
        "",
        "## 분석 설계",
        "",
        f"- SOFT DRINKS 선행 축소 고객-시점: {len(source):,}",
        "- 선행 축소: 핵심 카테고리인 SOFT DRINKS의 최근 8주 구매속도가 정상 기대치의 50% 미만",
        "- 노출: 기준 주부터 2주 이내 홈스토어에서 과거 구매 SOFT DRINKS 상품에 기록된 첫 프로모션",
        "- 처리: 구매이력 가중 결합 노출이 단독 노출보다 큰 고객-시점",
        "- 비교: 전단만 또는 진열만 가중 노출이 더 큰 고객-시점",
        "- 매칭: 과거 전체 매출, 최근 매출 추세, SOFT DRINKS 비중·구매속도, 위험 신호, 시점을 이용한 무복원 매칭",
        "- 결과: 이후 8주 SOFT DRINKS 재구매·매출과 전체 지출 유지율",
        "",
        "## 표본과 균형",
        "",
        f"- 주 분석 노출 확인 표본: {len(cohort):,}",
        f"- 결합 우세: {(cohort['exposure_group']=='combo').sum():,}, 단독 우세: {(cohort['exposure_group']=='single').sum():,}",
        f"- 매칭쌍: {int(repurchase['n_pairs']):,}",
        f"- 매칭 후 최대 절대 SMD: {max_smd:.3f}",
        "",
        "## 주 분석 결과",
        "",
        f"- SOFT DRINKS 재구매율: 결합 {repurchase['combo_mean']:.1%}, 단독 {repurchase['single_mean']:.1%}, 차이 {repurchase['effect']:+.1%}p",
        f"- 재구매율 95% CI: [{repurchase['ci_low']:+.1%}p, {repurchase['ci_high']:+.1%}p], p={repurchase['p_two_sided']:.4f}",
        f"- SOFT DRINKS 8주 매출 차이: {soft_revenue['effect']:+.2f} (95% CI {soft_revenue['ci_low']:+.2f}~{soft_revenue['ci_high']:+.2f})",
        f"- 전체 지출 유지율 차이: {total_retention['effect']:+.1f}%p (95% CI {total_retention['ci_low']:+.1f}~{total_retention['ci_high']:+.1f})",
        f"- 사전 전체 지출추세 placebo 차이: {placebo['effect']:+.3f} (95% CI {placebo['ci_low']:+.3f}~{placebo['ci_high']:+.3f})",
        "",
        "## 전체 표본 회귀 보정",
        "",
        f"- 보정 재구매율 효과: {adjusted_repurchase['adjusted_effect']:+.1%}p (95% CI {adjusted_repurchase['ci_low']:+.1%}p~{adjusted_repurchase['ci_high']:+.1%}p, p={adjusted_repurchase['p_value']:.4f})",
        f"- 보정 SOFT DRINKS 매출 효과: {adjusted_soft_revenue['adjusted_effect']:+.2f} (95% CI {adjusted_soft_revenue['ci_low']:+.2f}~{adjusted_soft_revenue['ci_high']:+.2f})",
        f"- 보정 전체 지출 유지율 효과: {adjusted_total['adjusted_effect']:+.1f}%p (95% CI {adjusted_total['ci_low']:+.1f}~{adjusted_total['ci_high']:+.1f})",
        "",
        "## 노출 창 민감도",
        "",
        "| 설정 | 매칭쌍 | 재구매율 차이 | 95% CI | p-value |",
        "| --- | ---: | ---: | --- | ---: |",
    ]
    for row in sensitivity.itertuples(index=False):
        lines.append(
            f"| {row.analysis} | {row.n_pairs} | {row.effect:+.1%}p | "
            f"[{row.ci_low:+.1%}p, {row.ci_high:+.1%}p] | {row.p_two_sided:.4f} |"
        )
    lines += [
        "",
        "## 해석 제한",
        "",
        "- 프로모션 가용성은 고객의 실제 전단 열람이나 진열 접촉을 보장하지 않는다.",
        "- 프로모션 배정은 무작위가 아니며 표본이 작으면 넓은 신뢰구간 때문에 효과를 배제하지 못할 수 있다.",
        "- 같은 고객이 여러 시점에 포함될 수 있어 신뢰구간은 처리 고객 단위 군집 부트스트랩으로 계산했다.",
        "- 유의한 결과가 나오더라도 실제 적용 전 고객 또는 매장 단위 무작위 실험이 필요하다.",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
