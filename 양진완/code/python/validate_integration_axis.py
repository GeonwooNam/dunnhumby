"""Validate product-response and customer-product integration marts."""

from __future__ import annotations

from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "integration_axis_outputs" / "integration_axis.duckdb"


CHECKS = {
    "product_store_response_unique": """
        SELECT COUNT(*) = COUNT(DISTINCT (PRODUCT_ID, STORE_ID, comparison))
        FROM mart_product_store_response_detail
    """,
    "product_profile_unique": """
        SELECT COUNT(*) = COUNT(DISTINCT (PRODUCT_ID, comparison))
        FROM mart_product_response_profile
    """,
    "main_profile_min_three_weeks": """
        SELECT COUNT(*) = 0
        FROM mart_product_response_profile AS p
        WHERE p.eligible_stores <> (
            SELECT COUNT(*)
            FROM mart_product_store_response_detail AS d
            WHERE d.PRODUCT_ID = p.PRODUCT_ID
              AND d.comparison = p.comparison
              AND d.min_state_weeks >= 3
        )
    """,
    "repeated_candidate_support": """
        SELECT COUNT(*) = 0
        FROM mart_product_response_profile
        WHERE is_repeated_any_positive = 1
          AND eligible_stores < 3
    """,
    "sales_candidate_rule": """
        SELECT COUNT(*) = 0
        FROM mart_product_response_profile
        WHERE is_repeated_sales_positive = 1
          AND NOT (
              eligible_stores >= 3
              AND median_spv_difference > 0
              AND positive_spv_store_pct >= 60
          )
    """,
    "penetration_candidate_rule": """
        SELECT COUNT(*) = 0
        FROM mart_product_response_profile
        WHERE is_repeated_penetration_positive = 1
          AND NOT (
              eligible_stores >= 3
              AND median_bpr_difference > 0
              AND positive_bpr_store_pct >= 60
          )
    """,
    "customer_fit_balanced": """
        SELECT COUNT(*) = 1099 * 4
           AND COUNT(DISTINCT household_key) = 1099
           AND COUNT(DISTINCT comparison) = 4
        FROM mart_customer_product_fit
    """,
    "customer_preference_weights_sum_one": """
        SELECT COUNT(*) = 0
        FROM mart_customer_product_fit
        WHERE ABS(total_preference_weight - 1.0) > 1e-9
    """,
    "customer_fit_weights_bounded": """
        SELECT COUNT(*) = 0
        FROM mart_customer_product_fit
        WHERE profiled_weight < -1e-9 OR profiled_weight > 1 + 1e-9
           OR multistore_profiled_weight < -1e-9
           OR multistore_profiled_weight > profiled_weight + 1e-9
           OR any_positive_weight < -1e-9
           OR any_positive_weight > multistore_profiled_weight + 1e-9
           OR home_store_profiled_weight < -1e-9
           OR home_store_profiled_weight > profiled_weight + 1e-9
    """,
    "strategy_shares_bounded": """
        SELECT COUNT(*) = 0
        FROM mart_customer_product_strategy_summary
        WHERE avg_strategy_candidate_share < -1e-9
           OR avg_strategy_candidate_share > 1 + 1e-9
           OR households_with_strategy_candidate_pct < -1e-9
           OR households_with_strategy_candidate_pct > 100 + 1e-9
    """,
    "expected_main_candidate_counts": """
        SELECT
            COUNT(*) FILTER (
                WHERE comparison = 'display_only_vs_none'
                  AND is_repeated_any_positive = 1
            ) = 32
        AND COUNT(*) FILTER (
                WHERE comparison = 'mailer_only_vs_none'
                  AND is_repeated_any_positive = 1
            ) = 33
        AND COUNT(*) FILTER (
                WHERE comparison = 'both_vs_none'
                  AND is_repeated_any_positive = 1
            ) = 33
        AND COUNT(*) FILTER (
                WHERE comparison = 'both_vs_additive'
                  AND is_repeated_any_positive = 1
            ) = 30
        FROM mart_product_response_profile
    """,
    "sensitivity_rows_complete": """
        SELECT COUNT(*) = 5 * 4
        FROM mart_product_response_support_sensitivity
    """,
    "customer_sensitivity_rows_complete": """
        SELECT COUNT(*) = 5 * 3
        FROM mart_customer_fit_support_sensitivity
    """,
}


def main() -> None:
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"Missing analysis database: {DB_PATH}")

    failures: list[str] = []
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        for name, sql in CHECKS.items():
            passed = bool(con.execute(sql).fetchone()[0])
            print(f"[{'PASS' if passed else 'FAIL'}] {name}")
            if not passed:
                failures.append(name)

    if failures:
        joined = ", ".join(failures)
        raise AssertionError(f"Integration validation failed: {joined}")
    print(f"All {len(CHECKS)} integration checks passed.")


if __name__ == "__main__":
    main()
