from pathlib import Path
import math

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
WIDE_PATH = DATA / "promotion_category_effects_wide.csv"
PRODUCT_EFFECTS_PATH = DATA / "promotion_robustness_product_effects.csv"
PRODUCT_PATH = ROOT / "product.csv"

DIRECTION_OUTPUT = DATA / "promotion_category_direction_candidates.csv"
PRIORITY_OUTPUT = DATA / "promotion_category_priority.csv"
PRODUCT_OUTPUT = DATA / "promotion_priority_products.csv"

DISPLAY = "진열+전단 - 진열만"
MAILER = "진열+전단 - 전단만"
COMPARISONS = [DISPLAY, MAILER]
MIN_PRODUCTS = 20
MIN_MATCHED_PAIRS = 200


def normal_summary(group, column):
    values = group[column].dropna().to_numpy(float)
    n = len(values)
    mean = float(values.mean()) if n else np.nan
    if n < 2:
        return mean, np.nan, np.nan, np.nan
    se = float(values.std(ddof=1) / np.sqrt(n))
    low, high = mean - 1.96 * se, mean + 1.96 * se
    z = mean / se if se > 0 else (np.inf if mean > 0 else 0)
    p = 0.5 * math.erfc(z / math.sqrt(2))
    return mean, low, high, p


# 2단계: 기존 카테고리 효과표에서 네 방향성 조건을 모두 만족하는 후보 선별
wide = pd.read_csv(WIDE_PATH)
direction_mask = (
    wide["has_both_comparisons"]
    & wide["sales_incidence_diff_vs_display_only"].gt(0)
    & wide["sales_incidence_diff_vs_mailer_only"].gt(0)
    & wide["revenue_diff_vs_display_only"].gt(0)
    & wide["revenue_diff_vs_mailer_only"].gt(0)
)
direction = wide.loc[direction_mask].copy()
direction["direction_pass"] = True
direction.to_csv(DIRECTION_OUTPUT, index=False, encoding="utf-8-sig")


# 3단계: 상품을 독립 분석 단위로 삼아 카테고리별 평균, 신뢰구간, 표본 규모 계산
effects = pd.read_csv(PRODUCT_EFFECTS_PATH)
effects = effects.loc[effects["tolerance_weeks"].eq(4)].copy()
products = pd.read_csv(
    PRODUCT_PATH,
    usecols=["PRODUCT_ID", "DEPARTMENT", "BRAND", "COMMODITY_DESC", "SUB_COMMODITY_DESC", "CURR_SIZE_OF_PRODUCT"],
)
effects = effects.merge(products, on="PRODUCT_ID", how="left", validate="many_to_one")

summary_rows = []
for (department, commodity, comparison), group in effects.groupby(
    ["DEPARTMENT", "COMMODITY_DESC", "comparison"], dropna=False
):
    sales_mean, sales_low, sales_high, sales_p = normal_summary(group, "sales_incidence_diff")
    revenue_mean, revenue_low, revenue_high, revenue_p = normal_summary(group, "revenue_diff")
    summary_rows.append(
        {
            "DEPARTMENT": department,
            "COMMODITY_DESC": commodity,
            "comparison": comparison,
            "products": group["PRODUCT_ID"].nunique(),
            "product_stores": int(group["product_stores"].sum()),
            "matched_pairs": int(group["matched_pairs"].sum()),
            "sales_incidence_mean": sales_mean,
            "sales_incidence_ci_low": sales_low,
            "sales_incidence_ci_high": sales_high,
            "sales_incidence_p_one_sided": sales_p,
            "revenue_mean": revenue_mean,
            "revenue_ci_low": revenue_low,
            "revenue_ci_high": revenue_high,
            "revenue_p_one_sided": revenue_p,
            "positive_product_share_sales": group["sales_incidence_diff"].gt(0).mean(),
            "positive_product_share_revenue": group["revenue_diff"].gt(0).mean(),
        }
    )

category_long = pd.DataFrame(summary_rows)
suffixes = {DISPLAY: "vs_display_only", MAILER: "vs_mailer_only"}
parts = []
metric_columns = [column for column in category_long.columns if column not in ["DEPARTMENT", "COMMODITY_DESC", "comparison"]]
for comparison, suffix in suffixes.items():
    part = category_long.loc[category_long["comparison"].eq(comparison), ["DEPARTMENT", "COMMODITY_DESC"] + metric_columns]
    part = part.rename(columns={column: f"{column}_{suffix}" for column in metric_columns})
    parts.append(part)
category = parts[0].merge(parts[1], on=["DEPARTMENT", "COMMODITY_DESC"], how="outer", validate="one_to_one")
category = category.merge(
    wide[["DEPARTMENT", "COMMODITY_DESC", "has_both_comparisons"]],
    on=["DEPARTMENT", "COMMODITY_DESC"], how="left", validate="one_to_one",
)
category = category.merge(
    direction[["DEPARTMENT", "COMMODITY_DESC", "direction_pass"]],
    on=["DEPARTMENT", "COMMODITY_DESC"], how="left", validate="one_to_one",
)
category["direction_pass"] = category["direction_pass"].fillna(False)

category["reliable_both"] = True
for suffix in suffixes.values():
    category["reliable_both"] &= (
        category[f"products_{suffix}"].ge(MIN_PRODUCTS)
        & category[f"matched_pairs_{suffix}"].ge(MIN_MATCHED_PAIRS)
        & category[f"sales_incidence_ci_low_{suffix}"].gt(0)
        & category[f"revenue_ci_low_{suffix}"].gt(0)
    )

category["conservative_sales_effect"] = category[
    ["sales_incidence_mean_vs_display_only", "sales_incidence_mean_vs_mailer_only"]
].min(axis=1)
category["conservative_revenue_effect"] = category[
    ["revenue_mean_vs_display_only", "revenue_mean_vs_mailer_only"]
].min(axis=1)
category["coverage_matched_pairs"] = category[
    ["matched_pairs_vs_display_only", "matched_pairs_vs_mailer_only"]
].min(axis=1)

reliable = category["reliable_both"]
category["priority_score"] = np.nan
if reliable.any():
    category.loc[reliable, "priority_score"] = (
        category.loc[reliable, "conservative_sales_effect"].rank(pct=True) * 0.4
        + category.loc[reliable, "conservative_revenue_effect"].rank(pct=True) * 0.4
        + np.log1p(category.loc[reliable, "coverage_matched_pairs"]).rank(pct=True) * 0.2
    )
    priority_cut = category.loc[reliable, "priority_score"].median()
else:
    priority_cut = np.nan

category["strategy_group"] = np.select(
    [
        category["reliable_both"] & category["priority_score"].ge(priority_cut),
        category["reliable_both"],
        category["direction_pass"],
        ~category["has_both_comparisons"].fillna(False),
    ],
    ["우선 적용", "안정적 적용 후보", "추가 실험 필요", "비교 자료 부족"],
    default="결합 근거 부족",
)
category["strategy_reason"] = np.select(
    [
        category["strategy_group"].eq("우선 적용"),
        category["strategy_group"].eq("안정적 적용 후보"),
        category["strategy_group"].eq("추가 실험 필요"),
        category["strategy_group"].eq("비교 자료 부족"),
    ],
    [
        "두 단독 방식 대비 판매발생률·매출의 95% 신뢰구간이 모두 0보다 크고, 효과·규모 종합점수가 상위권",
        "두 단독 방식 대비 판매발생률·매출의 95% 신뢰구간이 모두 0보다 크지만 우선 적용군보다 효과·규모 점수가 낮음",
        "평균 효과 방향은 모두 양수이나 표본 또는 신뢰구간 기준을 통과하지 못함",
        "진열만·전단만 중 하나와 비교할 자료가 없음",
    ],
    default="판매발생률·매출이 두 단독 방식보다 모두 높다는 조건을 충족하지 못함",
)
category = category.sort_values(
    ["strategy_group", "priority_score", "conservative_revenue_effect"],
    ascending=[True, False, False], kind="stable",
).reset_index(drop=True)
category.to_csv(PRIORITY_OUTPUT, index=False, encoding="utf-8-sig")


# 5단계: 우선 적용 카테고리 안에서 두 비교 모두 양수이고 표본이 있는 구체 상품 선별
priority_categories = category.loc[category["strategy_group"].eq("우선 적용"), ["DEPARTMENT", "COMMODITY_DESC"]]
priority_effects = effects.merge(priority_categories, on=["DEPARTMENT", "COMMODITY_DESC"], how="inner")
product_metrics = [
    "product_stores", "matched_pairs", "sales_incidence_diff", "revenue_diff", "units_diff", "baskets_diff"
]
product_parts = []
for comparison, suffix in suffixes.items():
    part = priority_effects.loc[priority_effects["comparison"].eq(comparison),
        ["PRODUCT_ID", "DEPARTMENT", "BRAND", "COMMODITY_DESC", "SUB_COMMODITY_DESC", "CURR_SIZE_OF_PRODUCT"] + product_metrics].copy()
    part = part.rename(columns={column: f"{column}_{suffix}" for column in product_metrics})
    product_parts.append(part)
product_wide = product_parts[0].merge(
    product_parts[1],
    on=["PRODUCT_ID", "DEPARTMENT", "BRAND", "COMMODITY_DESC", "SUB_COMMODITY_DESC", "CURR_SIZE_OF_PRODUCT"],
    how="inner", validate="one_to_one",
)
product_wide = product_wide.loc[
    product_wide["product_stores_vs_display_only"].ge(5)
    & product_wide["product_stores_vs_mailer_only"].ge(5)
    & product_wide["matched_pairs_vs_display_only"].ge(20)
    & product_wide["matched_pairs_vs_mailer_only"].ge(20)
    & product_wide["sales_incidence_diff_vs_display_only"].gt(0)
    & product_wide["sales_incidence_diff_vs_mailer_only"].gt(0)
    & product_wide["revenue_diff_vs_display_only"].gt(0)
    & product_wide["revenue_diff_vs_mailer_only"].gt(0)
].copy()
product_wide["conservative_sales_effect"] = product_wide[
    ["sales_incidence_diff_vs_display_only", "sales_incidence_diff_vs_mailer_only"]
].min(axis=1)
product_wide["conservative_revenue_effect"] = product_wide[
    ["revenue_diff_vs_display_only", "revenue_diff_vs_mailer_only"]
].min(axis=1)
product_wide["coverage_matched_pairs"] = product_wide[
    ["matched_pairs_vs_display_only", "matched_pairs_vs_mailer_only"]
].min(axis=1)
product_wide["product_score"] = (
    product_wide.groupby(["DEPARTMENT", "COMMODITY_DESC"])["conservative_sales_effect"].rank(pct=True) * 0.4
    + product_wide.groupby(["DEPARTMENT", "COMMODITY_DESC"])["conservative_revenue_effect"].rank(pct=True) * 0.4
    + np.log1p(product_wide["coverage_matched_pairs"]).groupby(
        [product_wide["DEPARTMENT"], product_wide["COMMODITY_DESC"]]
    ).rank(pct=True) * 0.2
)
product_wide["rank_within_category"] = product_wide.groupby(
    ["DEPARTMENT", "COMMODITY_DESC"]
)["product_score"].rank(method="first", ascending=False)
priority_products = product_wide.loc[product_wide["rank_within_category"].le(10)].sort_values(
    ["DEPARTMENT", "COMMODITY_DESC", "rank_within_category"]
)
priority_products.to_csv(PRODUCT_OUTPUT, index=False, encoding="utf-8-sig")

print(f"2단계 방향성 후보: {len(direction):,}")
print(f"3단계 신뢰도 통과: {category['reliable_both'].sum():,}")
print(category["strategy_group"].value_counts().to_string())
print("\n우선 적용 카테고리:")
print(category.loc[category["strategy_group"].eq("우선 적용"),
    ["DEPARTMENT", "COMMODITY_DESC", "conservative_sales_effect", "conservative_revenue_effect", "priority_score"]].to_string(index=False))
print(f"\n우선 상품 행: {len(priority_products):,}")
