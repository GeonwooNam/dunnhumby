from pathlib import Path
import math

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
TRANSACTION_PATH = ROOT / "transaction_data.csv"
CAUSAL_PATH = ROOT / "causal_data.csv"
PRODUCT_PATH = ROOT / "product.csv"

EVENT_OUTPUT = DATA / "customer_promotion_segment_event_effects.csv"
SUMMARY_OUTPUT = DATA / "customer_promotion_segment_summary.csv"
CHECK_OUTPUT = DATA / "customer_promotion_segment_checks.csv"
CONTRAST_OUTPUT = DATA / "customer_promotion_segment_contrasts.csv"

CATEGORIES = ["BACON", "LUNCHMEAT", "DINNER SAUSAGE"]
TOLERANCES = (1, 2, 4)
WEEKS = np.arange(1, 103, dtype=np.int16)


def mean_ci(values):
    values = pd.Series(values, dtype="float64").dropna().to_numpy()
    n = len(values)
    if n == 0:
        return n, np.nan, np.nan, np.nan, np.nan
    mean = float(values.mean())
    if n == 1:
        return n, mean, np.nan, np.nan, np.nan
    se = float(values.std(ddof=1) / math.sqrt(n))
    low = mean - 1.96 * se
    high = mean + 1.96 * se
    z = mean / se if se > 0 else (np.inf if mean > 0 else 0.0)
    p = math.erfc(abs(z) / math.sqrt(2))
    return n, mean, low, high, p


print("상품 정보 로드")
products = pd.read_csv(
    PRODUCT_PATH,
    usecols=["PRODUCT_ID", "DEPARTMENT", "COMMODITY_DESC"],
    dtype={"PRODUCT_ID": "int32", "DEPARTMENT": "string", "COMMODITY_DESC": "string"},
)
selected_products = products.loc[products["COMMODITY_DESC"].isin(CATEGORIES)].copy()
selected_ids = set(selected_products["PRODUCT_ID"].astype(int))

print("거래 데이터 로드")
tx = pd.read_csv(
    TRANSACTION_PATH,
    usecols=["household_key", "BASKET_ID", "PRODUCT_ID", "STORE_ID", "WEEK_NO", "SALES_VALUE"],
    dtype={
        "household_key": "int16",
        "BASKET_ID": "int64",
        "PRODUCT_ID": "int32",
        "STORE_ID": "int16",
        "WEEK_NO": "int16",
        "SALES_VALUE": "float32",
    },
)
tx = tx.merge(
    products[["PRODUCT_ID", "COMMODITY_DESC"]], on="PRODUCT_ID", how="left", validate="many_to_one"
)

# 행사 상품을 구매한 고객만 남기는 사후선택을 피하기 위해, 매장-주차의 모든 방문 고객을 적격자로 둔다.
shoppers = tx[["household_key", "STORE_ID", "WEEK_NO"]].drop_duplicates()

selected_tx = tx.loc[tx["COMMODITY_DESC"].isin(CATEGORIES)].copy()
product_customer_week = selected_tx.groupby(
    ["household_key", "PRODUCT_ID", "STORE_ID", "WEEK_NO"], as_index=False
).agg(product_revenue=("SALES_VALUE", "sum"), product_baskets=("BASKET_ID", "nunique"))
category_customer_week = selected_tx.groupby(
    ["household_key", "COMMODITY_DESC", "STORE_ID", "WEEK_NO"], as_index=False
).agg(category_revenue=("SALES_VALUE", "sum"), category_baskets=("BASKET_ID", "nunique"))

print("행사 전 26주 고객 세그먼트 생성")
households = np.sort(tx["household_key"].unique())
segment_grid = pd.MultiIndex.from_product(
    [households, CATEGORIES, WEEKS], names=["household_key", "COMMODITY_DESC", "WEEK_NO"]
).to_frame(index=False)
weekly_category = selected_tx.groupby(
    ["household_key", "COMMODITY_DESC", "WEEK_NO"], as_index=False
).agg(category_baskets_week=("BASKET_ID", "nunique"))
segment_grid = segment_grid.merge(
    weekly_category, on=["household_key", "COMMODITY_DESC", "WEEK_NO"], how="left"
)
segment_grid["category_baskets_week"] = segment_grid["category_baskets_week"].fillna(0)
segment_grid = segment_grid.sort_values(["household_key", "COMMODITY_DESC", "WEEK_NO"])
segment_grid["prior_26w_category_baskets"] = (
    segment_grid.groupby(["household_key", "COMMODITY_DESC"], sort=False)["category_baskets_week"]
    .transform(lambda s: s.shift(1).rolling(26, min_periods=1).sum())
    .fillna(0)
)
segment_grid["customer_segment"] = np.select(
    [
        segment_grid["prior_26w_category_baskets"].ge(3),
        segment_grid["prior_26w_category_baskets"].between(1, 2),
    ],
    ["충성고객(3회 이상)", "가끔 구매(1-2회)"],
    default="비구매(0회)",
)
segment_grid = segment_grid.drop(columns="category_baskets_week")

print("선정 카테고리 프로모션 행 추출")
causal_parts = []
for chunk in pd.read_csv(
    CAUSAL_PATH,
    usecols=["PRODUCT_ID", "STORE_ID", "WEEK_NO", "display", "mailer"],
    dtype={"PRODUCT_ID": "int32", "STORE_ID": "int16", "WEEK_NO": "int16", "display": "string", "mailer": "string"},
    chunksize=1_000_000,
):
    part = chunk.loc[chunk["PRODUCT_ID"].isin(selected_ids)].copy()
    if not part.empty:
        causal_parts.append(part)
causal = pd.concat(causal_parts, ignore_index=True)
causal["display_flag"] = causal["display"].fillna("0").ne("0")
causal["mailer_flag"] = causal["mailer"].fillna("0").ne("0")
causal = causal.groupby(["PRODUCT_ID", "STORE_ID", "WEEK_NO"], as_index=False).agg(
    display_flag=("display_flag", "max"), mailer_flag=("mailer_flag", "max")
)
causal["promo_group"] = np.select(
    [
        causal["display_flag"] & causal["mailer_flag"],
        causal["display_flag"] & ~causal["mailer_flag"],
        ~causal["display_flag"] & causal["mailer_flag"],
    ],
    ["combo", "display_only", "mailer_only"],
    default="none",
)
causal = causal.merge(
    selected_products[["PRODUCT_ID", "DEPARTMENT", "COMMODITY_DESC"]],
    on="PRODUCT_ID",
    how="left",
    validate="many_to_one",
)


def matched_events(tolerance, comparison_group):
    combo = causal.loc[
        causal["promo_group"].eq("combo"),
        ["PRODUCT_ID", "STORE_ID", "WEEK_NO", "DEPARTMENT", "COMMODITY_DESC"],
    ].copy()
    combo = combo.rename(columns={"WEEK_NO": "combo_week"})
    single = causal.loc[
        causal["promo_group"].eq(comparison_group), ["PRODUCT_ID", "STORE_ID", "WEEK_NO"]
    ].copy()
    single = single.rename(columns={"WEEK_NO": "single_week"})
    # merge_asof는 by 키뿐 아니라 전체 on 키가 단조 증가하도록 정렬되어야 한다.
    combo = combo.sort_values(["combo_week", "PRODUCT_ID", "STORE_ID"])
    single = single.sort_values(["single_week", "PRODUCT_ID", "STORE_ID"])
    matched = pd.merge_asof(
        combo,
        single,
        left_on="combo_week",
        right_on="single_week",
        by=["PRODUCT_ID", "STORE_ID"],
        direction="nearest",
        tolerance=tolerance,
    ).dropna(subset=["single_week"])
    matched["single_week"] = matched["single_week"].astype("int16")
    matched["tolerance_weeks"] = tolerance
    matched["comparison"] = {
        "display_only": "결합-진열만",
        "mailer_only": "결합-전단만",
    }[comparison_group]
    matched["event_id"] = np.arange(len(matched), dtype=np.int64)
    return matched


def event_segment_metrics(events, condition, week_column):
    keys = events[
        ["event_id", "PRODUCT_ID", "STORE_ID", week_column, "COMMODITY_DESC"]
    ].rename(columns={week_column: "WEEK_NO"})
    expanded = keys.merge(shoppers, on=["STORE_ID", "WEEK_NO"], how="inner", validate="many_to_many")
    expanded = expanded.merge(
        segment_grid,
        on=["household_key", "COMMODITY_DESC", "WEEK_NO"],
        how="left",
        validate="many_to_one",
    )
    expanded = expanded.merge(
        product_customer_week,
        on=["household_key", "PRODUCT_ID", "STORE_ID", "WEEK_NO"],
        how="left",
        validate="many_to_one",
    )
    expanded = expanded.merge(
        category_customer_week,
        on=["household_key", "COMMODITY_DESC", "STORE_ID", "WEEK_NO"],
        how="left",
        validate="many_to_one",
    )
    for column in ["product_revenue", "product_baskets", "category_revenue", "category_baskets"]:
        expanded[column] = expanded[column].fillna(0)
    expanded["product_buyer"] = expanded["product_baskets"].gt(0).astype(float)
    expanded["category_buyer"] = expanded["category_baskets"].gt(0).astype(float)
    metrics = expanded.groupby(["event_id", "customer_segment"], as_index=False).agg(
        eligible_customers=("household_key", "nunique"),
        product_buyer_rate=("product_buyer", "mean"),
        product_revenue_per_customer=("product_revenue", "mean"),
        category_buyer_rate=("category_buyer", "mean"),
        category_revenue_per_customer=("category_revenue", "mean"),
        mean_prior_26w_baskets=("prior_26w_category_baskets", "mean"),
    )
    return metrics.rename(
        columns={
            column: f"{condition}_{column}"
            for column in metrics.columns
            if column not in ["event_id", "customer_segment"]
        }
    )


print("고객군별 결합-단독 차이 계산")
event_parts = []
for tolerance in TOLERANCES:
    for comparison_group in ["display_only", "mailer_only"]:
        events = matched_events(tolerance, comparison_group)
        combo_metrics = event_segment_metrics(events, "combo", "combo_week")
        single_metrics = event_segment_metrics(events, "single", "single_week")
        metrics = combo_metrics.merge(
            single_metrics, on=["event_id", "customer_segment"], how="inner", validate="one_to_one"
        )
        metrics = metrics.merge(events, on="event_id", how="left", validate="many_to_one")
        for metric in [
            "product_buyer_rate",
            "product_revenue_per_customer",
            "category_buyer_rate",
            "category_revenue_per_customer",
        ]:
            metrics[f"{metric}_diff"] = metrics[f"combo_{metric}"] - metrics[f"single_{metric}"]
        event_parts.append(metrics)

event_effects = pd.concat(event_parts, ignore_index=True)
event_effects.to_csv(EVENT_OUTPUT, index=False, encoding="utf-8-sig")

# 같은 행사 사건 안에서 고객군별 결합 추가효과의 차이를 계산한다.
# 예: (결합-단독 효과 | 충성고객) - (결합-단독 효과 | 비구매고객)
contrast_parts = []
segment_pairs = [
    ("충성고객(3회 이상)", "비구매(0회)", "충성-비구매"),
    ("충성고객(3회 이상)", "가끔 구매(1-2회)", "충성-가끔"),
]
event_keys = [
    "tolerance_weeks", "comparison", "COMMODITY_DESC", "PRODUCT_ID", "STORE_ID", "event_id"
]
for metric in [
    "product_buyer_rate_diff",
    "product_revenue_per_customer_diff",
    "category_buyer_rate_diff",
    "category_revenue_per_customer_diff",
]:
    wide = event_effects.pivot_table(
        index=event_keys, columns="customer_segment", values=metric, aggfunc="first"
    ).reset_index()
    for left, right, label in segment_pairs:
        if left not in wide or right not in wide:
            continue
        part = wide[event_keys].copy()
        part["contrast"] = label
        part["metric"] = metric
        part["effect_difference"] = wide[left] - wide[right]
        contrast_parts.append(part.dropna(subset=["effect_difference"]))

contrast_events = pd.concat(contrast_parts, ignore_index=True)
contrast_cluster = contrast_events.groupby(
    ["tolerance_weeks", "comparison", "COMMODITY_DESC", "contrast", "metric", "PRODUCT_ID", "STORE_ID"],
    as_index=False,
).agg(events=("event_id", "nunique"), effect_difference=("effect_difference", "mean"))
contrast_rows = []
for keys, sample in contrast_cluster.groupby(
    ["tolerance_weeks", "comparison", "COMMODITY_DESC", "contrast", "metric"], sort=False
):
    tolerance, comparison, category, contrast, metric = keys
    n, mean, low, high, p = mean_ci(sample["effect_difference"])
    contrast_rows.append(
        {
            "tolerance_weeks": tolerance,
            "comparison": comparison,
            "COMMODITY_DESC": category,
            "contrast": contrast,
            "metric": metric,
            "product_store_clusters": n,
            "events": int(sample["events"].sum()),
            "effect_difference_mean": mean,
            "ci_low": low,
            "ci_high": high,
            "p_value": p,
        }
    )
contrasts = pd.DataFrame(contrast_rows)
contrasts.to_csv(CONTRAST_OUTPUT, index=False, encoding="utf-8-sig")

# 같은 상품-매장의 반복 행이 표준오차를 과도하게 작게 만들지 않도록 먼저 클러스터 평균을 낸다.
effect_metrics = [
    "product_buyer_rate_diff",
    "product_revenue_per_customer_diff",
    "category_buyer_rate_diff",
    "category_revenue_per_customer_diff",
]
cluster = event_effects.groupby(
    ["tolerance_weeks", "comparison", "COMMODITY_DESC", "customer_segment", "PRODUCT_ID", "STORE_ID"],
    as_index=False,
).agg(
    events=("event_id", "nunique"),
    combo_eligible_customers=("combo_eligible_customers", "sum"),
    single_eligible_customers=("single_eligible_customers", "sum"),
    **{metric: (metric, "mean") for metric in effect_metrics},
)

summary_rows = []
for keys, sample in cluster.groupby(
    ["tolerance_weeks", "comparison", "COMMODITY_DESC", "customer_segment"], sort=False
):
    tolerance, comparison, category, segment = keys
    base = {
        "tolerance_weeks": tolerance,
        "comparison": comparison,
        "COMMODITY_DESC": category,
        "customer_segment": segment,
        "product_store_clusters": len(sample),
        "events": int(sample["events"].sum()),
        "combo_customer_opportunities": int(sample["combo_eligible_customers"].sum()),
        "single_customer_opportunities": int(sample["single_eligible_customers"].sum()),
    }
    for metric in effect_metrics:
        n, mean, low, high, p = mean_ci(sample[metric])
        base[f"{metric}_mean"] = mean
        base[f"{metric}_ci_low"] = low
        base[f"{metric}_ci_high"] = high
        base[f"{metric}_p_value"] = p
    summary_rows.append(base)

summary = pd.DataFrame(summary_rows).sort_values(
    ["tolerance_weeks", "comparison", "COMMODITY_DESC", "customer_segment"]
)
summary.to_csv(SUMMARY_OUTPUT, index=False, encoding="utf-8-sig")

checks = pd.DataFrame(
    [
        {"check": "selected_products", "value": len(selected_products)},
        {"check": "selected_transactions", "value": len(selected_tx)},
        {"check": "selected_causal_rows_after_dedup", "value": len(causal)},
        {"check": "matched_event_segment_rows", "value": len(event_effects)},
        {"check": "missing_customer_segment", "value": int(event_effects["customer_segment"].isna().sum())},
    ]
)
checks.to_csv(CHECK_OUTPUT, index=False, encoding="utf-8-sig")

print(checks.to_string(index=False))
print("\n±4주 고객군별 요약")
display_columns = [
    "comparison", "COMMODITY_DESC", "customer_segment", "product_store_clusters", "events",
    "product_buyer_rate_diff_mean", "product_buyer_rate_diff_ci_low", "product_buyer_rate_diff_ci_high",
    "category_revenue_per_customer_diff_mean", "category_revenue_per_customer_diff_ci_low",
    "category_revenue_per_customer_diff_ci_high",
]
print(summary.loc[summary["tolerance_weeks"].eq(4), display_columns].to_string(index=False))
print(f"\n{SUMMARY_OUTPUT}")
print(CONTRAST_OUTPUT)
