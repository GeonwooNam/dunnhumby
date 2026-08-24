from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "processed" / "promotion_combination_category_effects.csv"
OUTPUT = ROOT / "data" / "processed" / "promotion_category_effects_wide.csv"

df = pd.read_csv(INPUT)
keys = ["DEPARTMENT", "COMMODITY_DESC"]
metrics = [
    "product_stores",
    "products",
    "matched_pairs",
    "sales_incidence_diff",
    "revenue_diff",
    "units_diff",
    "baskets_diff",
]
comparison_suffix = {
    "진열+전단 - 진열만": "vs_display_only",
    "진열+전단 - 전단만": "vs_mailer_only",
}

parts = []
for comparison, suffix in comparison_suffix.items():
    part = df.loc[df["comparison"].eq(comparison), keys + metrics].copy()
    part = part.rename(columns={column: f"{column}_{suffix}" for column in metrics})
    parts.append(part)

wide = parts[0].merge(parts[1], on=keys, how="outer", validate="one_to_one")
wide["has_display_comparison"] = wide["products_vs_display_only"].notna()
wide["has_mailer_comparison"] = wide["products_vs_mailer_only"].notna()
wide["has_both_comparisons"] = wide["has_display_comparison"] & wide["has_mailer_comparison"]

ordered = keys + [
    "has_display_comparison",
    "has_mailer_comparison",
    "has_both_comparisons",
    "products_vs_display_only",
    "product_stores_vs_display_only",
    "matched_pairs_vs_display_only",
    "sales_incidence_diff_vs_display_only",
    "revenue_diff_vs_display_only",
    "units_diff_vs_display_only",
    "baskets_diff_vs_display_only",
    "products_vs_mailer_only",
    "product_stores_vs_mailer_only",
    "matched_pairs_vs_mailer_only",
    "sales_incidence_diff_vs_mailer_only",
    "revenue_diff_vs_mailer_only",
    "units_diff_vs_mailer_only",
    "baskets_diff_vs_mailer_only",
]
wide = wide[ordered].sort_values(keys, kind="stable").reset_index(drop=True)
wide.to_csv(OUTPUT, index=False, encoding="utf-8-sig")

print(f"카테고리 행: {len(wide):,}")
print(f"두 비교 모두 존재: {wide['has_both_comparisons'].sum():,}")
print(f"진열만 비교만 존재: {(wide['has_display_comparison'] & ~wide['has_mailer_comparison']).sum():,}")
print(f"전단만 비교만 존재: {(~wide['has_display_comparison'] & wide['has_mailer_comparison']).sum():,}")
print(OUTPUT)
