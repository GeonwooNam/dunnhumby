"""Validate the product-category promotion extension and exported marts."""

from __future__ import annotations

from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "product_axis_outputs" / "product_axis.duckdb"


CHECKS = {
    "main matrix has one row per category": """
        SELECT COUNT(*) = COUNT(DISTINCT (DEPARTMENT, COMMODITY_DESC))
        FROM mart_category_promotion_matrix
    """,
    "main table has three direct rows plus one synergy row per category": """
        SELECT COUNT(*) = 4 * (
            SELECT COUNT(*) FROM mart_category_promotion_matrix
        )
        FROM mart_category_promotion_main
    """,
    "all main direct cells meet support floor": """
        SELECT COUNT(*) = 0
        FROM mart_category_promotion_main
        WHERE comparison IN (
            'display_only_vs_none', 'mailer_only_vs_none', 'both_vs_none'
        )
          AND (
              products < 5 OR product_store_pairs < 20 OR stores < 5
              OR has_adequate_support <> 1
          )
    """,
    "sales signals satisfy both aggregation levels": """
        SELECT COUNT(*) = 0
        FROM mart_category_promotion_response_sensitivity
        WHERE is_sales_signal = 1
          AND NOT (
              has_adequate_support = 1
              AND pair_median_spv_difference > 0
              AND positive_spv_pair_pct > 50
              AND median_product_spv_difference > 0
              AND positive_spv_product_pct > 50
          )
    """,
    "penetration signals satisfy both aggregation levels": """
        SELECT COUNT(*) = 0
        FROM mart_category_promotion_response_sensitivity
        WHERE is_penetration_signal = 1
          AND NOT (
              has_adequate_support = 1
              AND pair_median_bpr_difference > 0
              AND positive_bpr_pair_pct > 50
              AND median_product_bpr_difference > 0
              AND positive_bpr_product_pct > 50
          )
    """,
    "promising flag is the union of sales and penetration": """
        SELECT COUNT(*) = 0
        FROM mart_category_promotion_response_sensitivity
        WHERE is_promising <>
            CASE WHEN is_sales_signal = 1 OR is_penetration_signal = 1
                 THEN 1 ELSE 0 END
    """,
    "three-week stability never appears without a main candidate": """
        SELECT COUNT(*) = 0
        FROM mart_category_promotion_matrix
        WHERE display_stable_3week > is_display_candidate
           OR mailer_stable_3week > is_mailer_candidate
           OR both_stable_3week > is_both_candidate
           OR synergy_stable_3week > COALESCE(is_synergy_candidate, 0)
    """,
    "candidate count matches the three direct flags": """
        SELECT COUNT(*) = 0
        FROM mart_category_promotion_matrix
        WHERE candidate_promo_count <>
              is_display_candidate + is_mailer_candidate + is_both_candidate
    """,
    "sensitivity contains weeks one through three": """
        SELECT LIST(DISTINCT min_weeks ORDER BY min_weeks) = [1, 2, 3]
        FROM mart_category_promotion_response_sensitivity
    """,
}


def main() -> None:
    failures: list[str] = []
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        for label, sql in CHECKS.items():
            passed = bool(con.execute(sql).fetchone()[0])
            print(f"[{'PASS' if passed else 'FAIL'}] {label}")
            if not passed:
                failures.append(label)

        category_count = con.execute(
            "SELECT COUNT(*) FROM mart_category_promotion_matrix"
        ).fetchone()[0]
        candidate_cells = con.execute(
            """
            SELECT SUM(candidate_promo_count)
            FROM mart_category_promotion_matrix
            """
        ).fetchone()[0]
        print(f"[INFO] main categories: {category_count}")
        print(f"[INFO] promising direct category-promotion cells: {candidate_cells}")

    if failures:
        raise AssertionError("Validation failed: " + "; ".join(failures))


if __name__ == "__main__":
    main()
