from pathlib import Path
import math

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
EFFECTS_PATH = DATA / "promotion_robustness_product_effects.csv"
PRIORITY_PATH = DATA / "promotion_category_priority.csv"
PRODUCT_PATH = ROOT / "product.csv"
DETAIL_OUTPUT = DATA / "priority_category_robustness_tests.csv"
SUMMARY_OUTPUT = DATA / "priority_category_robustness_summary.csv"

MIN_PRODUCTS = 20
MIN_MATCHED_PAIRS = 200


def summarize(values):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    n = len(values)
    mean = values.mean() if n else np.nan
    if n < 2:
        return mean, np.nan, np.nan, np.nan
    se = values.std(ddof=1) / np.sqrt(n)
    low, high = mean - 1.96 * se, mean + 1.96 * se
    z = mean / se if se > 0 else (np.inf if mean > 0 else 0)
    p = 0.5 * math.erfc(z / math.sqrt(2))
    return mean, low, high, p


priority = pd.read_csv(PRIORITY_PATH)
priority = priority.loc[priority["strategy_group"].eq("우선 적용"), ["DEPARTMENT", "COMMODITY_DESC", "priority_score"]]
effects = pd.read_csv(EFFECTS_PATH)
products = pd.read_csv(PRODUCT_PATH, usecols=["PRODUCT_ID", "DEPARTMENT", "COMMODITY_DESC"])
effects = effects.merge(products, on="PRODUCT_ID", how="left", validate="many_to_one")
effects = effects.merge(priority, on=["DEPARTMENT", "COMMODITY_DESC"], how="inner", validate="many_to_one")

rows = []
for (department, commodity, tolerance, comparison), group in effects.groupby(
    ["DEPARTMENT", "COMMODITY_DESC", "tolerance_weeks", "comparison"]
):
    sales_mean, sales_low, sales_high, sales_p = summarize(group["sales_incidence_diff"])
    revenue_mean, revenue_low, revenue_high, revenue_p = summarize(group["revenue_diff"])
    products_n = group["PRODUCT_ID"].nunique()
    matched_pairs = int(group["matched_pairs"].sum())
    sufficient_sample = products_n >= MIN_PRODUCTS and matched_pairs >= MIN_MATCHED_PAIRS
    sales_pass = sufficient_sample and sales_low > 0
    revenue_pass = sufficient_sample and revenue_low > 0
    rows.append(
        {
            "DEPARTMENT": department,
            "COMMODITY_DESC": commodity,
            "tolerance_weeks": tolerance,
            "comparison": comparison,
            "products": products_n,
            "matched_pairs": matched_pairs,
            "sales_incidence_effect": sales_mean,
            "sales_ci_low": sales_low,
            "sales_ci_high": sales_high,
            "sales_p_one_sided": sales_p,
            "revenue_effect": revenue_mean,
            "revenue_ci_low": revenue_low,
            "revenue_ci_high": revenue_high,
            "revenue_p_one_sided": revenue_p,
            "sufficient_sample": sufficient_sample,
            "sales_pass": sales_pass,
            "revenue_pass": revenue_pass,
            "window_comparison_pass": sales_pass and revenue_pass,
            "direction_positive": sales_mean > 0 and revenue_mean > 0,
        }
    )

detail = pd.DataFrame(rows).sort_values(
    ["DEPARTMENT", "COMMODITY_DESC", "tolerance_weeks", "comparison"]
)
detail.to_csv(DETAIL_OUTPUT, index=False, encoding="utf-8-sig")

summary = detail.groupby(["DEPARTMENT", "COMMODITY_DESC"]).agg(
    checks=("window_comparison_pass", "size"),
    passed_checks=("window_comparison_pass", "sum"),
    positive_direction_checks=("direction_positive", "sum"),
    min_sales_effect=("sales_incidence_effect", "min"),
    max_sales_effect=("sales_incidence_effect", "max"),
    min_revenue_effect=("revenue_effect", "min"),
    max_revenue_effect=("revenue_effect", "max"),
    min_products=("products", "min"),
    min_matched_pairs=("matched_pairs", "min"),
).reset_index()
summary = summary.merge(priority, on=["DEPARTMENT", "COMMODITY_DESC"], how="left", validate="one_to_one")
summary["final_recommendation"] = np.select(
    [summary["passed_checks"].eq(summary["checks"]), summary["positive_direction_checks"].eq(summary["checks"])],
    ["최우선 적용", "파일럿"],
    default="우선순위 하향",
)
summary["recommendation_reason"] = np.select(
    [summary["final_recommendation"].eq("최우선 적용"), summary["final_recommendation"].eq("파일럿")],
    [
        "±1·±2·±4주의 두 단독 방식 비교에서 판매발생률·매출 95% 신뢰구간 하한이 모두 0 초과",
        "모든 조건에서 평균 효과는 양수지만 일부 조건의 신뢰구간이 0을 포함",
    ],
    default="일부 기간 또는 비교에서 판매발생률·매출 평균 효과가 0 이하",
)
summary = summary.sort_values(
    ["final_recommendation", "passed_checks", "priority_score"], ascending=[True, False, False]
).reset_index(drop=True)
summary.to_csv(SUMMARY_OUTPUT, index=False, encoding="utf-8-sig")

print(detail.groupby(["DEPARTMENT", "COMMODITY_DESC"])["window_comparison_pass"].agg(["sum", "count"]).to_string())
print("\n최종 판정")
print(summary[["DEPARTMENT", "COMMODITY_DESC", "passed_checks", "checks", "final_recommendation"]].to_string(index=False))
