from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
HISTORICAL_PATH = DATA / "spend_decline_rolling_backtest_customers.csv"
REPORT_PATH = ROOT / "reports" / "current_customer_monitoring_summary.md"
CURRENT_WEEK = 101
BASELINE_START = 68
BASELINE_END = 93
RECENT_START = 94
RECENT_END = 101


def risk_tier(diversity_ratio):
    return np.select(
        [diversity_ratio < 0.70, diversity_ratio < 0.85],
        ["개입 검토", "관찰"],
        default="정상",
    )


def decline_pattern(frequency_ratio, basket_value_ratio):
    frequency_down = frequency_ratio < 0.70
    basket_down = basket_value_ratio < 0.85
    return np.select(
        [frequency_down & ~basket_down, ~frequency_down & basket_down, frequency_down & basket_down],
        ["빈도 감소", "회당금액 감소", "빈도·회당금액 동반 감소"],
        default="뚜렷한 구조 변화 없음",
    )


def historical_calibration(history):
    data = history.copy()
    data["risk_tier"] = risk_tier(data["diversity_ratio"])
    data["loss_fraction"] = (1 - data["future_revenue_ratio"]).clip(lower=0)
    calibration = data.groupby("risk_tier").agg(
        historical_customer_periods=("household_key", "size"),
        historical_unique_customers=("household_key", "nunique"),
        decline_probability=("spend_decline_30pct", "mean"),
        mean_loss_fraction=("loss_fraction", "mean"),
        median_loss_fraction=("loss_fraction", "median"),
    ).reset_index()
    return calibration


def main():
    history = pd.read_csv(HISTORICAL_PATH)
    calibration = historical_calibration(history)

    tx = pd.read_csv(
        ROOT / "transaction_data.csv",
        usecols=["household_key", "BASKET_ID", "DAY", "PRODUCT_ID", "SALES_VALUE", "STORE_ID", "WEEK_NO"],
    )
    products = pd.read_csv(ROOT / "product.csv", usecols=["PRODUCT_ID", "DEPARTMENT", "COMMODITY_DESC"])
    tx = tx.merge(products, on="PRODUCT_ID", how="left", validate="many_to_one")
    tx = tx.loc[
        tx["WEEK_NO"].between(BASELINE_START, RECENT_END)
        & ~tx["DEPARTMENT"].isin(["KIOSK-GAS", "MISC SALES TRAN", "MISC. TRANS."])
    ].copy()
    baseline = tx.loc[tx["WEEK_NO"].between(BASELINE_START, BASELINE_END)].copy()
    recent = tx.loc[tx["WEEK_NO"].between(RECENT_START, RECENT_END)].copy()

    active_weeks = baseline.groupby("household_key")["WEEK_NO"].nunique()
    eligible = active_weeks.loc[active_weeks >= 8].index
    baseline_revenue = baseline.groupby("household_key")["SALES_VALUE"].sum()
    cutoff = baseline_revenue.loc[baseline_revenue.index.isin(eligible)].quantile(0.8)
    high_value = baseline_revenue.loc[
        baseline_revenue.index.isin(eligible) & baseline_revenue.ge(cutoff)
    ].index
    baseline = baseline.loc[baseline["household_key"].isin(high_value)]
    recent = recent.loc[recent["household_key"].isin(high_value)]

    baseline_metrics = baseline.groupby("household_key").agg(
        baseline_revenue=("SALES_VALUE", "sum"),
        baseline_baskets=("BASKET_ID", "nunique"),
        baseline_active_weeks=("WEEK_NO", "nunique"),
        baseline_last_day=("DAY", "max"),
    )
    recent_metrics = recent.groupby("household_key").agg(
        recent_revenue=("SALES_VALUE", "sum"),
        recent_baskets=("BASKET_ID", "nunique"),
        recent_active_weeks=("WEEK_NO", "nunique"),
        recent_categories=("COMMODITY_DESC", "nunique"),
        recent_last_day=("DAY", "max"),
    )
    monitor = baseline_metrics.merge(recent_metrics, on="household_key", how="left")
    for column in ["recent_revenue", "recent_baskets", "recent_active_weeks", "recent_categories"]:
        monitor[column] = monitor[column].fillna(0)
    monitor["baseline_weekly_revenue"] = monitor["baseline_revenue"] / 26
    monitor["recent_weekly_revenue"] = monitor["recent_revenue"] / 8
    monitor["recent_revenue_ratio"] = monitor["recent_weekly_revenue"] / monitor["baseline_weekly_revenue"]
    monitor["baseline_baskets_per_week"] = monitor["baseline_baskets"] / 26
    monitor["recent_baskets_per_week"] = monitor["recent_baskets"] / 8
    monitor["basket_frequency_ratio"] = monitor["recent_baskets_per_week"] / monitor["baseline_baskets_per_week"]
    monitor["baseline_avg_basket_value"] = monitor["baseline_revenue"] / monitor["baseline_baskets"]
    monitor["recent_avg_basket_value"] = monitor["recent_revenue"] / monitor["recent_baskets"].replace(0, np.nan)
    monitor["recent_avg_basket_value"] = monitor["recent_avg_basket_value"].fillna(0)
    monitor["avg_basket_value_ratio"] = monitor["recent_avg_basket_value"] / monitor["baseline_avg_basket_value"]
    monitor["recency_days"] = int(tx["DAY"].max()) - monitor["recent_last_day"].fillna(monitor["baseline_last_day"])

    diversity_windows = []
    for end_week in range(BASELINE_START + 7, BASELINE_END + 1):
        diversity_windows.append(
            baseline.loc[baseline["WEEK_NO"].between(end_week - 7, end_week)]
            .groupby("household_key")["COMMODITY_DESC"]
            .nunique()
            .rename(end_week)
        )
    usual_diversity = pd.concat(diversity_windows, axis=1).median(axis=1)
    monitor["usual_category_diversity"] = usual_diversity
    monitor["diversity_ratio"] = monitor["recent_categories"] / monitor["usual_category_diversity"]
    monitor["risk_tier"] = risk_tier(monitor["diversity_ratio"])
    monitor["current_decline_pattern"] = decline_pattern(
        monitor["basket_frequency_ratio"], monitor["avg_basket_value_ratio"]
    )

    baseline_category = baseline.groupby(["household_key", "COMMODITY_DESC"]).agg(
        category_revenue=("SALES_VALUE", "sum"), category_baskets=("BASKET_ID", "nunique")
    ).reset_index()
    baseline_category["category_rank"] = baseline_category.groupby("household_key")["category_revenue"].rank(
        method="first", ascending=False
    )
    core = baseline_category.loc[
        baseline_category["category_rank"].le(3) & baseline_category["category_baskets"].ge(3)
    ].copy()
    recent_category = recent.groupby(["household_key", "COMMODITY_DESC"])["BASKET_ID"].nunique().rename(
        "recent_category_baskets"
    ).reset_index()
    core = core.merge(recent_category, on=["household_key", "COMMODITY_DESC"], how="left")
    core["recent_category_baskets"] = core["recent_category_baskets"].fillna(0)
    core["expected_recent_baskets"] = core["category_baskets"] / 26 * 8
    core["category_pace_ratio"] = core["recent_category_baskets"] / core["expected_recent_baskets"]
    contracted = core.loc[core["category_pace_ratio"].lt(0.50)].copy()
    contracted = contracted.sort_values(["household_key", "category_revenue"], ascending=[True, False])
    contracted_names = contracted.groupby("household_key")["COMMODITY_DESC"].agg(lambda x: " | ".join(x)).rename(
        "contracted_core_categories"
    )
    contracted_count = contracted.groupby("household_key").size().rename("contracted_core_category_count")
    monitor = monitor.merge(contracted_names, on="household_key", how="left").merge(
        contracted_count, on="household_key", how="left"
    )
    monitor["contracted_core_categories"] = monitor["contracted_core_categories"].fillna("")
    monitor["contracted_core_category_count"] = monitor["contracted_core_category_count"].fillna(0).astype(int)

    monitor = monitor.reset_index().merge(calibration, on="risk_tier", how="left")
    monitor["expected_8w_revenue_loss"] = (
        monitor["baseline_weekly_revenue"] * 8 * monitor["mean_loss_fraction"]
    )
    tier_order = pd.Categorical(monitor["risk_tier"], categories=["개입 검토", "관찰", "정상"], ordered=True)
    monitor["risk_tier"] = tier_order
    monitor = monitor.sort_values(
        ["risk_tier", "expected_8w_revenue_loss", "diversity_ratio"], ascending=[True, False, True]
    )
    monitor["priority_rank"] = np.arange(1, len(monitor) + 1)
    monitor["snapshot_week"] = CURRENT_WEEK

    tier_summary = monitor.groupby("risk_tier", observed=True).agg(
        customers=("household_key", "size"),
        baseline_weekly_revenue=("baseline_weekly_revenue", "sum"),
        expected_8w_revenue_loss=("expected_8w_revenue_loss", "sum"),
        median_diversity_ratio=("diversity_ratio", "median"),
        median_recent_revenue_ratio=("recent_revenue_ratio", "median"),
        contracted_core_share=("contracted_core_category_count", lambda x: (x > 0).mean()),
    ).reset_index()
    monitor.to_csv(DATA / "current_high_value_customer_monitor.csv", index=False, encoding="utf-8-sig")
    tier_summary.to_csv(DATA / "current_high_value_customer_monitor_summary.csv", index=False, encoding="utf-8-sig")
    contracted.to_csv(DATA / "current_high_value_contracted_categories.csv", index=False, encoding="utf-8-sig")

    intervention = monitor.loc[monitor["risk_tier"].eq("개입 검토")]
    watch = monitor.loc[monitor["risk_tier"].eq("관찰")]
    pattern_summary = intervention["current_decline_pattern"].value_counts()
    intervention_categories = contracted.loc[contracted["household_key"].isin(intervention["household_key"])]
    category_summary = intervention_categories.groupby("COMMODITY_DESC").agg(
        customers=("household_key", "nunique"),
        baseline_category_revenue=("category_revenue", "sum"),
        median_pace_ratio=("category_pace_ratio", "median"),
    ).reset_index().sort_values(["customers", "baseline_category_revenue"], ascending=False)
    lines = [
        "# W101 고가치 고객 지출 감소 모니터링",
        "",
        "## 운영 기준",
        "",
        f"- 정상 기준기간: W{BASELINE_START}-W{BASELINE_END}",
        f"- 최근 신호기간: W{RECENT_START}-W{RECENT_END}",
        f"- 고가치 기준: 활동주차 8주 이상 고객 중 기준기간 지출 상위 20% (컷 {cutoff:,.2f})",
        "- 개입 검토: 최근 카테고리 다양성이 평소의 70% 미만",
        "- 관찰: 최근 카테고리 다양성이 평소의 70%-85% 미만",
        "- 정상: 최근 카테고리 다양성이 평소의 85% 이상",
        "- 위험률과 예상 손실액은 6개 과거 이동 백테스트의 단계별 평균을 적용한 운영 참고치",
        "",
        "## 현재 규모",
        "",
        f"- 모니터링 고가치 고객: {len(monitor):,}명",
        f"- 개입 검토: {len(intervention):,}명",
        f"- 관찰: {len(watch):,}명",
        f"- 개입 검토 고객의 기준 주매출 합계: {intervention['baseline_weekly_revenue'].sum():,.1f}",
        f"- 개입 검토 고객의 보정 예상 8주 감소 매출: {intervention['expected_8w_revenue_loss'].sum():,.1f}",
        "",
        "## 개입 검토 고객의 현재 감소 구조",
        "",
        "| 구조 | 고객 | 비중 |",
        "| --- | ---: | ---: |",
    ]
    for pattern, count in pattern_summary.items():
        lines.append(f"| {pattern} | {count} | {count / len(intervention):.1%} |")
    lines += [
        "",
        "## 개입 검토군에서 많이 축소된 핵심 카테고리",
        "",
        "| 카테고리 | 고객 | 기준기간 카테고리 매출 | 최근 구매속도 중앙값 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in category_summary.head(10).itertuples(index=False):
        lines.append(
            f"| {row.COMMODITY_DESC} | {row.customers} | {row.baseline_category_revenue:,.1f} | {row.median_pace_ratio:.1%} |"
        )
    lines += [
        "",
        "## 단계별 요약",
        "",
        "| 단계 | 고객 | 과거 감소확률 | 기준 주매출 | 예상 8주 감소매출 | 다양성 비율 중앙값 | 최근 지출비율 중앙값 | 핵심카테고리 축소 비율 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    calibration_map = calibration.set_index("risk_tier")
    for row in tier_summary.itertuples(index=False):
        probability = calibration_map.loc[str(row.risk_tier), "decline_probability"]
        lines.append(
            f"| {row.risk_tier} | {row.customers} | {probability:.1%} | {row.baseline_weekly_revenue:,.1f} | "
            f"{row.expected_8w_revenue_loss:,.1f} | {row.median_diversity_ratio:.1%} | "
            f"{row.median_recent_revenue_ratio:.1%} | {row.contracted_core_share:.1%} |"
        )
    lines += [
        "",
        "## 사용 원칙",
        "",
        "- 이 명단은 개입 효과가 검증된 고객 목록이 아니라 지출 감소 가능성이 높은 검토 순위다.",
        "- 예상 감소 매출은 고객별 예측모델 값이 아니라 과거 위험 단계 평균을 적용한 자원배분 참고치다.",
        "- 실제 개입 수단은 무작위 배정해 비교하며, 프로모션 상품 추천과 자동 연결하지 않는다.",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
