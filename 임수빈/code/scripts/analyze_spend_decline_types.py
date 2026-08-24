from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
COHORT_PATH = DATA / "spend_decline_rolling_backtest_customers.csv"
REPORT_PATH = ROOT / "reports" / "spend_decline_type_analysis.md"
ORIGINS = [50, 58, 66, 74, 82, 90]
BASELINE_WEEKS = 26
FOLLOWUP_WEEKS = 8


def safe_ratio(numerator, denominator):
    return np.divide(
        numerator,
        denominator,
        out=np.full_like(np.asarray(numerator, dtype=float), np.nan),
        where=np.asarray(denominator) != 0,
    )


def classify_driver(data):
    frequency_down = data["basket_frequency_ratio"].lt(0.70)
    basket_value_down = data["avg_basket_value_ratio"].lt(0.85)
    return np.select(
        [frequency_down & ~basket_value_down, ~frequency_down & basket_value_down, frequency_down & basket_value_down],
        ["방문·구매빈도 중심", "회당 구매금액 중심", "빈도·구매금액 동반"],
        default="완만한 복합 감소",
    )


def customer_metrics(tx, cohort, origin):
    baseline_start = origin - 33
    baseline_end = origin - 8
    baseline = tx.loc[tx["WEEK_NO"].between(baseline_start, baseline_end)].copy()
    future = tx.loc[tx["WEEK_NO"].between(origin + 1, origin + FOLLOWUP_WEEKS)].copy()
    ids = cohort["household_key"].unique()
    baseline = baseline.loc[baseline["household_key"].isin(ids)]
    future = future.loc[future["household_key"].isin(ids)]

    baseline_metrics = baseline.groupby("household_key").agg(
        baseline_baskets=("BASKET_ID", "nunique"),
        baseline_active_weeks=("WEEK_NO", "nunique"),
        baseline_products=("PRODUCT_ID", "nunique"),
    )
    future_metrics = future.groupby("household_key").agg(
        future_baskets=("BASKET_ID", "nunique"),
        future_active_weeks=("WEEK_NO", "nunique"),
        future_products=("PRODUCT_ID", "nunique"),
        future_categories=("COMMODITY_DESC", "nunique"),
    )
    result = cohort.merge(baseline_metrics, on="household_key", how="left").merge(
        future_metrics, on="household_key", how="left"
    )
    for column in ["future_baskets", "future_active_weeks", "future_products", "future_categories"]:
        result[column] = result[column].fillna(0)
    result["baseline_baskets_per_week"] = result["baseline_baskets"] / BASELINE_WEEKS
    result["future_baskets_per_week"] = result["future_baskets"] / FOLLOWUP_WEEKS
    result["basket_frequency_ratio"] = safe_ratio(
        result["future_baskets_per_week"], result["baseline_baskets_per_week"]
    )
    result["baseline_avg_basket_value"] = safe_ratio(result["baseline_revenue"], result["baseline_baskets"])
    result["future_avg_basket_value"] = safe_ratio(result["future_8w_revenue"], result["future_baskets"])
    result["future_avg_basket_value"] = result["future_avg_basket_value"].fillna(0)
    result["avg_basket_value_ratio"] = safe_ratio(
        result["future_avg_basket_value"], result["baseline_avg_basket_value"]
    )
    result["active_week_ratio"] = safe_ratio(
        result["future_active_weeks"] / FOLLOWUP_WEEKS,
        result["baseline_active_weeks"] / BASELINE_WEEKS,
    )
    result["future_diversity_ratio"] = safe_ratio(
        result["future_categories"], result["usual_category_diversity"]
    )

    baseline_category = baseline.groupby(["household_key", "COMMODITY_DESC"]).agg(
        category_baseline_revenue=("SALES_VALUE", "sum"),
        category_baseline_baskets=("BASKET_ID", "nunique"),
    ).reset_index()
    baseline_category["category_rank"] = baseline_category.groupby("household_key")[
        "category_baseline_revenue"
    ].rank(method="first", ascending=False)
    future_category = future.groupby(["household_key", "COMMODITY_DESC"]).agg(
        category_future_revenue=("SALES_VALUE", "sum"),
        category_future_baskets=("BASKET_ID", "nunique"),
    ).reset_index()
    repeated = baseline_category.loc[
        baseline_category["category_baseline_baskets"].ge(3)
        & baseline_category["category_rank"].le(3)
    ].merge(
        future_category, on=["household_key", "COMMODITY_DESC"], how="left"
    )
    repeated[["category_future_revenue", "category_future_baskets"]] = repeated[
        ["category_future_revenue", "category_future_baskets"]
    ].fillna(0)
    repeated["category_stopped"] = repeated["category_future_baskets"].eq(0)
    repeated["stopped_baseline_revenue"] = repeated["category_baseline_revenue"].where(
        repeated["category_stopped"], 0
    )
    stopped = repeated.groupby("household_key").agg(
        repeated_categories=("COMMODITY_DESC", "size"),
        stopped_repeated_categories=("category_stopped", "sum"),
        stopped_category_baseline_revenue=("stopped_baseline_revenue", "sum"),
    )
    stopped_only = repeated.loc[repeated["category_stopped"]].copy()
    dominant = (
        stopped_only.sort_values(
            ["household_key", "category_baseline_revenue", "COMMODITY_DESC"],
            ascending=[True, False, True],
        )
        .drop_duplicates("household_key")
        .set_index("household_key")["COMMODITY_DESC"]
        .rename("dominant_stopped_category")
    )
    result = result.merge(stopped, on="household_key", how="left").merge(dominant, on="household_key", how="left")
    for column in ["repeated_categories", "stopped_repeated_categories", "stopped_category_baseline_revenue"]:
        result[column] = result[column].fillna(0)
    result["stopped_category_revenue_share"] = safe_ratio(
        result["stopped_category_baseline_revenue"], result["baseline_revenue"]
    )
    result["any_repeated_category_stopped"] = result["stopped_repeated_categories"].gt(0)
    result["decline_driver"] = classify_driver(result)
    result["high_precision_alert"] = result["diversity_ratio"].lt(0.70)
    result["watchlist_alert"] = result["diversity_ratio"].lt(0.85)
    return result


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

    parts = []
    for origin in ORIGINS:
        origin_cohort = cohort.loc[cohort["origin_week"].eq(origin)].copy()
        parts.append(customer_metrics(tx, origin_cohort, origin))
    detail = pd.concat(parts, ignore_index=True)
    declines = detail.loc[detail["spend_decline_30pct"]].copy()

    type_summary = declines.groupby("decline_driver").agg(
        customer_periods=("household_key", "size"),
        unique_customers=("household_key", "nunique"),
        median_revenue_ratio=("future_revenue_ratio", "median"),
        total_revenue_loss=("revenue_loss", "sum"),
        median_basket_frequency_ratio=("basket_frequency_ratio", "median"),
        median_avg_basket_value_ratio=("avg_basket_value_ratio", "median"),
        median_future_diversity_ratio=("future_diversity_ratio", "median"),
        stopped_category_share=("any_repeated_category_stopped", "mean"),
        high_precision_alert_rate=("high_precision_alert", "mean"),
        watchlist_alert_rate=("watchlist_alert", "mean"),
    ).reset_index()
    type_summary["observation_share"] = type_summary["customer_periods"] / len(declines)
    type_summary["loss_share"] = type_summary["total_revenue_loss"] / declines["revenue_loss"].sum()
    type_summary = type_summary.sort_values("total_revenue_loss", ascending=False)

    category_summary = (
        declines.loc[declines["dominant_stopped_category"].notna()]
        .groupby("dominant_stopped_category")
        .agg(
            customer_periods=("household_key", "size"),
            unique_customers=("household_key", "nunique"),
            total_revenue_loss=("revenue_loss", "sum"),
            median_revenue_loss=("revenue_loss", "median"),
            median_stopped_revenue_share=("stopped_category_revenue_share", "median"),
            high_precision_alert_rate=("high_precision_alert", "mean"),
        )
        .reset_index()
        .sort_values(["total_revenue_loss", "customer_periods"], ascending=False)
    )

    detail.to_csv(DATA / "spend_decline_type_customer_periods.csv", index=False, encoding="utf-8-sig")
    type_summary.to_csv(DATA / "spend_decline_type_summary.csv", index=False, encoding="utf-8-sig")
    category_summary.to_csv(DATA / "spend_decline_stopped_category_summary.csv", index=False, encoding="utf-8-sig")

    frequency_related = declines["decline_driver"].isin(["방문·구매빈도 중심", "빈도·구매금액 동반"])
    basket_related = declines["decline_driver"].isin(["회당 구매금액 중심", "빈도·구매금액 동반"])
    stopped_rate = declines["any_repeated_category_stopped"].mean()
    nondecline_stopped_rate = detail.loc[~detail["spend_decline_30pct"], "any_repeated_category_stopped"].mean()
    stopped_rate_ratio = stopped_rate / nondecline_stopped_rate
    top_categories = category_summary.loc[category_summary["customer_periods"].ge(5)].head(10)
    lines = [
        "# 고가치 고객 지출 감소 유형 분석",
        "",
        "## 분석 대상과 기준",
        "",
        f"- 6개 이동 시점의 고가치 고객-시점 관측치: {len(detail):,}",
        f"- 이후 8주 지출이 평소보다 30% 이상 감소한 관측치: {len(declines):,}",
        "- 구매빈도 감소: 주평균 장바구니 수가 평소의 70% 미만",
        "- 회당 구매금액 감소: 평균 장바구니 금액이 평소의 85% 미만",
        "- 핵심 카테고리 중단: 기준기간 매출 상위 3개이면서 3개 이상 장바구니에서 구매했지만 이후 8주 구매가 0인 카테고리",
        "- 유형은 구매빈도와 회당 구매금액 조건으로 상호배타적으로 분류하고, 카테고리 중단은 별도 중첩 지표로 본다.",
        "",
        "## 핵심 결과",
        "",
        f"- 구매빈도 감소가 포함된 유형: {frequency_related.mean():.1%}",
        f"- 회당 구매금액 감소가 포함된 유형: {basket_related.mean():.1%}",
        f"- 핵심 카테고리가 하나 이상 완전히 중단된 비율: {stopped_rate:.1%}",
        f"- 비감소 고객의 핵심 카테고리 중단률: {nondecline_stopped_rate:.1%} (감소 고객이 {stopped_rate_ratio:.2f}배)",
        f"- 70% 다양성 경보가 포착한 감소 관측치: {declines['high_precision_alert'].mean():.1%}",
        f"- 85% 관찰 경보가 포착한 감소 관측치: {declines['watchlist_alert'].mean():.1%}",
        "",
        "## 감소 유형별 결과",
        "",
        "| 유형 | 관측치 | 비중 | 손실 비중 | 지출 유지율 중앙값 | 빈도 비율 | 회당금액 비율 | 카테고리 중단률 | 70% 경보 포착률 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in type_summary.itertuples(index=False):
        lines.append(
            f"| {row.decline_driver} | {row.customer_periods} | {row.observation_share:.1%} | {row.loss_share:.1%} | "
            f"{row.median_revenue_ratio:.1%} | {row.median_basket_frequency_ratio:.1%} | "
            f"{row.median_avg_basket_value_ratio:.1%} | {row.stopped_category_share:.1%} | "
            f"{row.high_precision_alert_rate:.1%} |"
        )
    lines += [
        "",
        "## 주요 중단 카테고리",
        "",
        "아래 표는 감소 고객의 과거 핵심 카테고리 중 이후 8주 완전히 구매하지 않은 항목에서 기준 매출이 가장 컸던 카테고리다. 동일 고객이 여러 시점에 포함될 수 있으며, 인과적 감소 원인으로 단정하지 않는다.",
        "",
        "| 카테고리 | 관측치 | 고객 | 총 감소 매출 | 중앙 감소 매출 | 중단 카테고리 과거 매출 비중 | 70% 경보 포착률 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in top_categories.itertuples(index=False):
        lines.append(
            f"| {row.dominant_stopped_category} | {row.customer_periods} | {row.unique_customers} | "
            f"{row.total_revenue_loss:,.1f} | {row.median_revenue_loss:,.1f} | "
            f"{row.median_stopped_revenue_share:.1%} | {row.high_precision_alert_rate:.1%} |"
        )
    lines += [
        "",
        "## 해석 원칙",
        "",
        "- 빈도 중심 감소가 우세하면 방문을 유도하는 개입을, 회당 구매금액 중심이면 장바구니 확대 개입을 별도로 실험해야 한다.",
        "- 카테고리 중단은 결과기간에 지출 감소와 함께 측정한 진단 신호이며 조기 경보 변수가 아니다. 해당 카테고리 프로모션이 지출을 회복시킨다는 뜻도 아니다.",
        "- 중단 카테고리는 고객별 개입 후보를 만드는 근거가 아니라 후속 무작위 실험의 층화 변수로 우선 사용한다.",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
