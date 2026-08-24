from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
COHORT_PATH = DATA / "spend_decline_rolling_backtest_customers.csv"
REPORT_PATH = ROOT / "reports" / "leading_category_contraction_analysis.md"
ORIGINS = [50, 58, 66, 74, 82, 90]
BASELINE_WEEKS = 26
RECENT_WEEKS = 8
SHRINK_THRESHOLD = 0.50
PROMOTION_CANDIDATES = {
    "BACON": "최우선",
    "LUNCHMEAT": "최우선",
    "DINNER SAUSAGE": "최우선",
    "BREAKFAST SAUSAGE/SANDWICHES": "추가 파일럿",
    "SOFT DRINKS": "추가 파일럿",
    "PIES": "추가 파일럿",
    "WAREHOUSE SNACKS": "추가 파일럿",
}
RANDOM_SEED = 42


def cluster_bootstrap_risk_difference(data, n_boot=2000):
    grouped = []
    for _, group in data.groupby("household_key"):
        grouped.append(
            np.array(
                [
                    ((group["category_contracted"] & group["spend_decline_30pct"]).sum()),
                    group["category_contracted"].sum(),
                    ((~group["category_contracted"] & group["spend_decline_30pct"]).sum()),
                    (~group["category_contracted"]).sum(),
                ],
                dtype=float,
            )
        )
    clusters = np.vstack(grouped)
    rng = np.random.default_rng(RANDOM_SEED)
    diffs = []
    for _ in range(n_boot):
        sample = clusters[rng.integers(0, len(clusters), size=len(clusters))].sum(axis=0)
        if sample[1] and sample[3]:
            diffs.append(sample[0] / sample[1] - sample[2] / sample[3])
    return np.quantile(diffs, [0.025, 0.975]) if diffs else (np.nan, np.nan)


def build_category_rows(tx, cohort, origin):
    baseline_start = origin - 33
    baseline_end = origin - 8
    recent_start = origin - 7
    ids = cohort["household_key"].unique()
    baseline = tx.loc[
        tx["WEEK_NO"].between(baseline_start, baseline_end) & tx["household_key"].isin(ids)
    ]
    recent = tx.loc[tx["WEEK_NO"].between(recent_start, origin) & tx["household_key"].isin(ids)]

    baseline_category = baseline.groupby(["household_key", "COMMODITY_DESC"]).agg(
        baseline_category_revenue=("SALES_VALUE", "sum"),
        baseline_category_baskets=("BASKET_ID", "nunique"),
    ).reset_index()
    baseline_category["category_rank"] = baseline_category.groupby("household_key")[
        "baseline_category_revenue"
    ].rank(method="first", ascending=False)
    core = baseline_category.loc[
        baseline_category["category_rank"].le(3) & baseline_category["baseline_category_baskets"].ge(3)
    ].copy()
    recent_category = recent.groupby(["household_key", "COMMODITY_DESC"]).agg(
        recent_category_revenue=("SALES_VALUE", "sum"),
        recent_category_baskets=("BASKET_ID", "nunique"),
    ).reset_index()
    core = core.merge(recent_category, on=["household_key", "COMMODITY_DESC"], how="left")
    core[["recent_category_revenue", "recent_category_baskets"]] = core[
        ["recent_category_revenue", "recent_category_baskets"]
    ].fillna(0)
    core["expected_recent_baskets"] = core["baseline_category_baskets"] / BASELINE_WEEKS * RECENT_WEEKS
    core["category_basket_pace_ratio"] = (
        core["recent_category_baskets"] / core["expected_recent_baskets"].replace(0, np.nan)
    )
    core["category_contracted"] = core["category_basket_pace_ratio"].lt(SHRINK_THRESHOLD)
    core["category_stopped_recently"] = core["recent_category_baskets"].eq(0)
    core["origin_week"] = origin
    outcome_columns = [
        "household_key", "spend_decline_30pct", "future_revenue_ratio", "revenue_loss",
        "baseline_weekly_revenue", "diversity_ratio",
    ]
    return core.merge(cohort[outcome_columns], on="household_key", how="inner")


def summarize_category(group):
    contracted = group["category_contracted"]
    decline = group["spend_decline_30pct"]
    contract_rate = decline.loc[contracted].mean()
    stable_rate = decline.loc[~contracted].mean()
    comparable_origins = 0
    positive_origins = 0
    for _, period in group.groupby("origin_week"):
        if period["category_contracted"].sum() >= 2 and (~period["category_contracted"]).sum() >= 2:
            comparable_origins += 1
            positive_origins += (
                period.loc[period["category_contracted"], "spend_decline_30pct"].mean()
                > period.loc[~period["category_contracted"], "spend_decline_30pct"].mean()
            )
    ci_low, ci_high = cluster_bootstrap_risk_difference(group)
    return pd.Series(
        {
            "customer_period_categories": len(group),
            "unique_customers": group["household_key"].nunique(),
            "contracted_observations": int(contracted.sum()),
            "stable_observations": int((~contracted).sum()),
            "decline_rate_contracted": contract_rate,
            "decline_rate_stable": stable_rate,
            "risk_difference": contract_rate - stable_rate,
            "risk_difference_ci_low": ci_low,
            "risk_difference_ci_high": ci_high,
            "relative_risk": contract_rate / stable_rate if stable_rate else np.nan,
            "median_loss_contracted": group.loc[contracted, "revenue_loss"].median(),
            "median_loss_stable": group.loc[~contracted, "revenue_loss"].median(),
            "comparable_origins": comparable_origins,
            "positive_origins": positive_origins,
            "positive_origin_share": positive_origins / comparable_origins if comparable_origins else np.nan,
        }
    )


def main():
    cohort = pd.read_csv(COHORT_PATH)
    tx = pd.read_csv(
        ROOT / "transaction_data.csv",
        usecols=["household_key", "BASKET_ID", "PRODUCT_ID", "SALES_VALUE", "WEEK_NO"],
    )
    product = pd.read_csv(ROOT / "product.csv", usecols=["PRODUCT_ID", "DEPARTMENT", "COMMODITY_DESC"])
    tx = tx.merge(product, on="PRODUCT_ID", how="left", validate="many_to_one")
    tx = tx.loc[
        tx["WEEK_NO"].between(17, 101)
        & ~tx["DEPARTMENT"].isin(["KIOSK-GAS", "MISC SALES TRAN", "MISC. TRANS."])
    ].copy()

    detail = pd.concat(
        [
            build_category_rows(tx, cohort.loc[cohort["origin_week"].eq(origin)].copy(), origin)
            for origin in ORIGINS
        ],
        ignore_index=True,
    )
    eligible_categories = detail.groupby("COMMODITY_DESC").filter(
        lambda g: len(g) >= 30 and g["category_contracted"].sum() >= 10 and (~g["category_contracted"]).sum() >= 10
    )
    summary = (
        eligible_categories.groupby("COMMODITY_DESC", group_keys=False)
        .apply(summarize_category, include_groups=False)
        .reset_index()
    )
    summary["robust_candidate"] = (
        summary["risk_difference_ci_low"].gt(0)
        & summary["comparable_origins"].ge(3)
        & summary["positive_origin_share"].ge(2 / 3)
    )
    summary["promotion_priority_overlap"] = summary["COMMODITY_DESC"].isin(PROMOTION_CANDIDATES)
    summary = summary.sort_values(
        ["robust_candidate", "risk_difference", "contracted_observations"], ascending=[False, False, False]
    )

    overall = summarize_category(detail)
    robust = summary.loc[summary["robust_candidate"]].copy()
    detail.to_csv(DATA / "leading_category_contraction_customer_categories.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(DATA / "leading_category_contraction_summary.csv", index=False, encoding="utf-8-sig")
    robust.to_csv(DATA / "leading_category_contraction_robust_candidates.csv", index=False, encoding="utf-8-sig")

    lines = [
        "# 지출 감소 전 핵심 카테고리 축소 분석",
        "",
        "## 질문과 설계",
        "",
        "> 고객의 과거 핵심 카테고리 구매속도가 기준 시점 직전부터 크게 줄면 이후 8주 전체 지출 감소 가능성이 높아지는가?",
        "",
        "- 핵심 카테고리: 정상 기준기간 매출 상위 3개이면서 3개 이상 장바구니에서 구매",
        "- 정상 구매속도: 26주 기준기간의 카테고리 장바구니 수를 8주 기대치로 환산",
        f"- 선행 축소: 최근 8주 장바구니 수가 정상 기대치의 {SHRINK_THRESHOLD:.0%} 미만",
        "- 결과: 그다음 8주 전체 지출이 평소보다 30% 이상 감소",
        "- 안정 후보: 축소·비축소 각각 10건 이상, 전체 30건 이상, 고객 군집 부트스트랩 위험차 CI 하한 > 0, 비교 가능 시점의 2/3 이상에서 같은 방향",
        "",
        "## 전체 핵심 카테고리 수준 결과",
        "",
        f"- 고객×시점×핵심카테고리 관측치: {int(overall['customer_period_categories']):,}",
        f"- 선행 축소 관측치: {int(overall['contracted_observations']):,}",
        f"- 축소 시 이후 지출 감소율: {overall['decline_rate_contracted']:.1%}",
        f"- 비축소 시 이후 지출 감소율: {overall['decline_rate_stable']:.1%}",
        f"- 위험도 차이: {overall['risk_difference']:+.1%}p (95% CI {overall['risk_difference_ci_low']:+.1%}p~{overall['risk_difference_ci_high']:+.1%}p)",
        f"- 상대위험: {overall['relative_risk']:.2f}배",
        "",
        "## 안정 후보 카테고리",
        "",
        "| 카테고리 | 축소 표본 | 축소 감소율 | 비축소 감소율 | 위험차 | 95% CI | 시점 방향 | 상대위험 |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for row in robust.head(15).itertuples(index=False):
        lines.append(
            f"| {row.COMMODITY_DESC} | {int(row.contracted_observations)} | {row.decline_rate_contracted:.1%} | "
            f"{row.decline_rate_stable:.1%} | {row.risk_difference:+.1%}p | "
            f"[{row.risk_difference_ci_low:+.1%}p, {row.risk_difference_ci_high:+.1%}p] | "
            f"{int(row.positive_origins)}/{int(row.comparable_origins)} | {row.relative_risk:.2f} |"
        )
    if robust.empty:
        lines.append("| 안정 기준을 모두 통과한 카테고리 없음 | - | - | - | - | - | - | - |")

    lines += [
        "",
        "## 기존 결합 프로모션 후보와의 교집합",
        "",
        "| 카테고리 | 기존 등급 | 분석 가능 | 선행축소 안정 후보 | 축소 감소율 | 비축소 감소율 | 위험차 |",
        "| --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    for category, tier in PROMOTION_CANDIDATES.items():
        row = summary.loc[summary["COMMODITY_DESC"].eq(category)]
        if row.empty:
            lines.append(f"| {category} | {tier} | 아니오 | 아니오 | - | - | - |")
        else:
            r = row.iloc[0]
            lines.append(
                f"| {category} | {tier} | 예 | {'예' if r.robust_candidate else '아니오'} | "
                f"{r.decline_rate_contracted:.1%} | {r.decline_rate_stable:.1%} | {r.risk_difference:+.1%}p |"
            )
    lines += [
        "",
        "## 해석",
        "",
        "- 이 분석은 카테고리 축소를 미래 결과보다 먼저 측정하므로 결과기간 중단 분석보다 조기 경보 근거에 가깝다.",
        "- 카테고리별 비교는 탐색적 다중 비교다. 안정 후보는 효과 확정이 아니라 후속 실험 층화 후보로 사용한다.",
        "- 기존 결합 프로모션 우선 카테고리와 안정 후보가 겹쳐도, 해당 프로모션이 고객 전체 지출 감소를 막는다는 인과효과는 별도 무작위 실험이 필요하다.",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
