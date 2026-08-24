from pathlib import Path
import math

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
TRANSACTION_PATH = ROOT / "transaction_data.csv"
CAUSAL_PATH = ROOT / "causal_data.csv"
PRODUCT_PATH = ROOT / "product.csv"
PRODUCT_OUTPUT = DATA / "promotion_synergy_product_effects.csv"
TEST_OUTPUT = DATA / "promotion_synergy_hypothesis_tests.csv"
SUMMARY_OUTPUT = DATA / "promotion_synergy_summary.csv"

KEYS = ["PRODUCT_ID", "STORE_ID", "WEEK_NO"]
OUTCOMES = ["has_sale", "revenue", "units", "baskets", "retail_discount", "coupon_discount"]
TOLERANCES = (1, 2, 4)
CHUNK_SIZE = 1_000_000


tx = pd.read_csv(
    TRANSACTION_PATH,
    usecols=["BASKET_ID", "PRODUCT_ID", "STORE_ID", "WEEK_NO", "QUANTITY", "SALES_VALUE",
             "RETAIL_DISC", "COUPON_DISC", "COUPON_MATCH_DISC"],
    dtype={"BASKET_ID": "int64", "PRODUCT_ID": "int32", "STORE_ID": "int32", "WEEK_NO": "int16",
           "QUANTITY": "int32", "SALES_VALUE": "float32", "RETAIL_DISC": "float32",
           "COUPON_DISC": "float32", "COUPON_MATCH_DISC": "float32"},
)
tx_week = tx.groupby(KEYS).agg(
    revenue=("SALES_VALUE", "sum"), units=("QUANTITY", "sum"), baskets=("BASKET_ID", "nunique"),
    retail_discount=("RETAIL_DISC", "sum"), coupon_discount=("COUPON_DISC", "sum"),
    coupon_match_discount=("COUPON_MATCH_DISC", "sum"),
)
tx_week[["retail_discount", "coupon_discount", "coupon_match_discount"]] *= -1


def match_group(combo, comparison, label):
    columns = KEYS + OUTCOMES
    comp = comparison[columns].copy()
    comp[f"week_{label}"] = comp["WEEK_NO"]
    comp = comp.rename(columns={outcome: f"{outcome}_{label}" for outcome in OUTCOMES})
    return pd.merge_asof(
        combo.sort_values("WEEK_NO"), comp.sort_values("WEEK_NO"),
        on="WEEK_NO", by=["PRODUCT_ID", "STORE_ID"], direction="nearest", tolerance=4,
    )


def product_effects_for_block(causal):
    causal["display_flag"] = causal["display"].fillna("0").ne("0")
    causal["mailer_flag"] = causal["mailer"].fillna("0").ne("0")
    # 원본에는 동일 PRODUCT_ID-STORE_ID-WEEK_NO가 여러 행인 경우가 있다.
    # 한 키에서 어느 한 행이라도 채널이 켜져 있으면 해당 채널 적용으로 통합한다.
    causal = causal.groupby(KEYS, as_index=False).agg(
        display_flag=("display_flag", "max"), mailer_flag=("mailer_flag", "max")
    )
    causal["promo_group"] = np.select(
        [
            causal["display_flag"] & causal["mailer_flag"],
            causal["display_flag"] & ~causal["mailer_flag"],
            ~causal["display_flag"] & causal["mailer_flag"],
        ],
        ["combo", "display_only", "mailer_only"], default="none",
    )
    # causal_data는 전단 또는 특별 진열이 있었던 상품-매장-주차만 기록한다.
    # 결합 주차 주변(±4주)에서 causal_data에 없는 키를 '전단·진열 미적용' 후보로 파생한다.
    combo_keys = causal.loc[causal["promo_group"].eq("combo"), KEYS]
    none_parts = []
    for offset in range(-max(TOLERANCES), max(TOLERANCES) + 1):
        if offset == 0:
            continue
        candidate = combo_keys.copy()
        candidate["WEEK_NO"] = candidate["WEEK_NO"] + offset
        candidate = candidate.loc[candidate["WEEK_NO"].between(1, 102)]
        none_parts.append(candidate)
    none = pd.concat(none_parts, ignore_index=True).drop_duplicates(KEYS)
    promo_keys = causal[KEYS].drop_duplicates()
    none = none.merge(promo_keys.assign(_promo=1), on=KEYS, how="left")
    none = none.loc[none["_promo"].isna(), KEYS].copy()
    none["display_flag"] = False
    none["mailer_flag"] = False
    none["promo_group"] = "none"

    causal = pd.concat([causal, none], ignore_index=True, sort=False)
    causal = causal.join(tx_week, on=KEYS)
    for column in ["revenue", "units", "baskets", "retail_discount", "coupon_discount",
                   "coupon_match_discount"]:
        causal[column] = causal[column].fillna(0)
    causal["has_sale"] = causal["revenue"].gt(0).astype(int)

    combo = causal.loc[causal["promo_group"].eq("combo"), KEYS + OUTCOMES].copy()
    if combo.empty:
        return []
    combo = combo.rename(columns={outcome: f"{outcome}_combo" for outcome in OUTCOMES})
    for group_name, label in [("display_only", "display"), ("mailer_only", "mailer"), ("none", "none")]:
        comparison = causal.loc[causal["promo_group"].eq(group_name)]
        if comparison.empty:
            return []
        combo = match_group(combo, comparison, label)
    combo = combo.dropna(subset=["week_display", "week_mailer", "week_none"])
    if combo.empty:
        return []
    for label in ["display", "mailer", "none"]:
        combo[f"distance_{label}"] = (combo["WEEK_NO"] - combo[f"week_{label}"]).abs()
    combo["max_week_distance"] = combo[["distance_display", "distance_mailer", "distance_none"]].max(axis=1)
    for outcome in OUTCOMES:
        combo[f"{outcome}_synergy"] = (
            combo[f"{outcome}_combo"] - combo[f"{outcome}_display"]
            - combo[f"{outcome}_mailer"] + combo[f"{outcome}_none"]
        )

    results = []
    level_columns = [f"{outcome}_{group}" for outcome in OUTCOMES for group in ["combo", "display", "mailer", "none"]]
    synergy_columns = [f"{outcome}_synergy" for outcome in OUTCOMES]
    for tolerance in TOLERANCES:
        pairs = combo.loc[combo["max_week_distance"].le(tolerance)]
        if pairs.empty:
            continue
        agg = {"matched_quads": ("WEEK_NO", "size"), "mean_max_week_distance": ("max_week_distance", "mean")}
        agg.update({column: (column, "mean") for column in level_columns + synergy_columns})
        store = pairs.groupby(["PRODUCT_ID", "STORE_ID"]).agg(**agg).reset_index()
        product_agg = {
            "product_stores": ("STORE_ID", "nunique"),
            "matched_quads": ("matched_quads", "sum"),
            "mean_max_week_distance": ("mean_max_week_distance", "mean"),
        }
        product_agg.update({column: (column, "mean") for column in level_columns + synergy_columns})
        product = store.groupby("PRODUCT_ID").agg(**product_agg).reset_index()
        product["tolerance_weeks"] = tolerance
        results.append(product)
    return results


effect_parts = []
carry = pd.DataFrame()
previous_last_product = None
dtype = {"PRODUCT_ID": "int32", "STORE_ID": "int32", "WEEK_NO": "int16", "display": "string", "mailer": "string"}
for chunk_no, chunk in enumerate(pd.read_csv(CAUSAL_PATH, chunksize=CHUNK_SIZE, dtype=dtype), start=1):
    if previous_last_product is not None and chunk["PRODUCT_ID"].iloc[0] < previous_last_product:
        raise ValueError("causal_data가 PRODUCT_ID 순으로 정렬되어 있지 않습니다.")
    previous_last_product = int(chunk["PRODUCT_ID"].iloc[-1])
    if not carry.empty:
        chunk = pd.concat([carry, chunk], ignore_index=True)
    last_product = chunk["PRODUCT_ID"].iloc[-1]
    carry = chunk.loc[chunk["PRODUCT_ID"].eq(last_product)].copy()
    complete = chunk.loc[~chunk["PRODUCT_ID"].eq(last_product)].copy()
    if not complete.empty:
        effect_parts.extend(product_effects_for_block(complete))
    if chunk_no % 10 == 0:
        print(f"{chunk_no}개 청크 처리 완료")
effect_parts.extend(product_effects_for_block(carry))
product_effects = pd.concat(effect_parts, ignore_index=True)

product_info = pd.read_csv(PRODUCT_PATH, usecols=["PRODUCT_ID", "DEPARTMENT", "COMMODITY_DESC"])
product_effects = product_effects.merge(product_info, on="PRODUCT_ID", how="left", validate="many_to_one")
product_effects.to_csv(PRODUCT_OUTPUT, index=False, encoding="utf-8-sig")


def normal_test(values):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    n = len(values)
    mean = values.mean() if n else np.nan
    if n < 2:
        return n, mean, np.nan, np.nan, np.nan, np.nan
    se = values.std(ddof=1) / np.sqrt(n)
    low, high = mean - 1.96 * se, mean + 1.96 * se
    z = mean / se if se > 0 else (np.inf if mean > 0 else 0)
    p_one_sided = 0.5 * math.erfc(z / math.sqrt(2))
    p_two_sided = min(1.0, 2 * min(p_one_sided, 1 - p_one_sided))
    return n, mean, low, high, p_one_sided, p_two_sided


scopes = {
    "전체": pd.Series(True, index=product_effects.index),
    "BACON": product_effects["COMMODITY_DESC"].eq("BACON"),
    "LUNCHMEAT": product_effects["COMMODITY_DESC"].eq("LUNCHMEAT"),
    "DINNER SAUSAGE": product_effects["COMMODITY_DESC"].eq("DINNER SAUSAGE"),
}
outcome_names = {
    "has_sale": "판매발생률", "revenue": "매출", "units": "판매수량", "baskets": "장바구니 수",
    "retail_discount": "소매할인액", "coupon_discount": "쿠폰할인액",
}
test_rows = []
for scope, mask in scopes.items():
    for tolerance in TOLERANCES:
        sample = product_effects.loc[mask & product_effects["tolerance_weeks"].eq(tolerance)]
        for outcome, outcome_name in outcome_names.items():
            n, mean, low, high, p, p_two = normal_test(sample[f"{outcome}_synergy"])
            if np.isfinite(low) and low > 0:
                verdict = "양의 시너지"
            elif np.isfinite(high) and high < 0:
                verdict = "음의 상호작용"
            else:
                verdict = "가산효과와 구분 불가"
            test_rows.append(
                {
                    "scope": scope, "tolerance_weeks": tolerance, "outcome": outcome_name,
                    "products": n, "matched_quads": int(sample["matched_quads"].sum()),
                    "mean_synergy": mean, "ci_low": low, "ci_high": high,
                    "p_value_one_sided_positive": p, "p_value_two_sided": p_two, "verdict": verdict,
                }
            )
tests = pd.DataFrame(test_rows)
tests.to_csv(TEST_OUTPUT, index=False, encoding="utf-8-sig")

summary = tests.loc[tests["outcome"].isin(["판매발생률", "매출"])].pivot_table(
    index=["scope", "tolerance_weeks"], columns="outcome",
    values=["products", "mean_synergy", "ci_low", "ci_high", "verdict"], aggfunc="first",
).reset_index()
summary.columns = ["_".join([str(part) for part in column if str(part)]) if isinstance(column, tuple) else column for column in summary.columns]
summary["both_positive_synergy"] = (
    summary["verdict_판매발생률"].eq("양의 시너지") & summary["verdict_매출"].eq("양의 시너지")
)
summary.to_csv(SUMMARY_OUTPUT, index=False, encoding="utf-8-sig")

print(f"상품 효과 행: {len(product_effects):,}")
print(tests.loc[tests["outcome"].isin(["판매발생률", "매출"])].to_string(index=False))
