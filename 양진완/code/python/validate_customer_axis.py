"""Run structural and result-regression checks on the customer-axis database."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parent
ANALYSIS_DB = ROOT / "customer_axis_outputs" / "customer_axis.duckdb"


@dataclass
class Check:
    name: str
    sql: str
    expected: float
    tolerance: float = 0.0


CHECKS = [
    Check(
        "top20_weights_sum_to_one",
        """
        SELECT COALESCE(MAX(ABS(weight_sum - 1)), 0)
        FROM (
            SELECT household_key, SUM(preference_weight_top20) AS weight_sum
            FROM work_customer_preference GROUP BY 1
        )
        """,
        0.0,
        1e-10,
    ),
    Check(
        "top10_weights_sum_to_one",
        """
        SELECT COALESCE(MAX(ABS(weight_sum - 1)), 0)
        FROM (
            SELECT household_key, SUM(preference_weight_top10) AS weight_sum
            FROM work_customer_preference GROUP BY 1
        )
        """,
        0.0,
        1e-10,
    ),
    Check(
        "exposure_key_duplicates",
        """
        SELECT COUNT(*) - COUNT(DISTINCT (household_key, WEEK_NO))
        FROM mart_customer_week_exposure
        """,
        0.0,
    ),
    Check(
        "panel_key_duplicates",
        """
        SELECT COUNT(*) - COUNT(DISTINCT (household_key, WEEK_NO))
        FROM mart_customer_week_panel
        """,
        0.0,
    ),
    Check(
        "candidate_exposure_row_count_difference",
        """
        SELECT ABS(
            (SELECT COUNT(*) FROM mart_customer_week_exposure)
            - 75 * (SELECT COUNT(*) FROM work_analysis_customer
                    WHERE is_candidate_analysis = 1)
        )
        """,
        0.0,
    ),
    Check(
        "candidate_panel_row_count_difference",
        """
        SELECT ABS(
            (SELECT COUNT(*) FROM mart_customer_week_panel)
            - 75 * (SELECT COUNT(*) FROM work_analysis_customer
                    WHERE is_candidate_analysis = 1)
        )
        """,
        0.0,
    ),
    Check(
        "exposure_out_of_range_rows",
        """
        SELECT COUNT(*)
        FROM mart_customer_week_exposure
        WHERE any_feature_exposure NOT BETWEEN 0 AND 1
           OR feature_mailer_exposure NOT BETWEEN 0 AND 1
           OR display_exposure NOT BETWEEN 0 AND 1
           OR both_exposure NOT BETWEEN 0 AND 1
           OR coupon_mailer_exposure NOT BETWEEN 0 AND 1
           OR free_mailer_exposure NOT BETWEEN 0 AND 1
           OR promo_record_weight NOT BETWEEN 0 AND 1
           OR conflict_weight NOT BETWEEN 0 AND 1
        """,
        0.0,
    ),
    Check(
        "null_main_exposure_rows",
        """
        SELECT COUNT(*)
        FROM mart_customer_week_exposure
        WHERE any_feature_exposure IS NULL
           OR feature_mailer_exposure IS NULL
           OR display_exposure IS NULL
           OR both_exposure IS NULL
        """,
        0.0,
    ),
    Check(
        "invalid_preference_exclusion_share_rows",
        """
        SELECT COUNT(*)
        FROM work_analysis_customer
        WHERE is_candidate_analysis = 1
          AND (excluded_weight_share IS NULL
               OR excluded_weight_share NOT BETWEEN 0 AND 1)
        """,
        0.0,
    ),
    Check(
        "primary_panel_missing_baseline_diagnostics",
        """
        SELECT COUNT(*)
        FROM mart_customer_week_panel
        WHERE is_primary_analysis = 1
          AND (n_baseline_purchase_weeks IS NULL
               OR baseline_home_store_share IS NULL
               OR excluded_weight_share IS NULL)
        """,
        0.0,
    ),
    Check(
        "primary_households_have_five_eligible_products",
        """
        SELECT COUNT(*)
        FROM work_analysis_customer
        WHERE is_primary_analysis = 1
          AND n_eligible_products < 5
        """,
        0.0,
    ),
    Check(
        "primary_preferences_use_baseline_history_only",
        """
        SELECT COUNT(*)
        FROM work_customer_preference AS p
        LEFT JOIN work_home_store_product_history AS h
          ON p.PRODUCT_ID = h.PRODUCT_ID
         AND p.home_store_id = h.STORE_ID
        WHERE h.PRODUCT_ID IS NULL
        """,
        0.0,
    ),
    Check(
        "all_weeks_sensitivity_weights_sum_to_one",
        """
        SELECT COALESCE(MAX(ABS(weight_sum - 1)), 0)
        FROM (
            SELECT household_key, SUM(preference_weight_top20) AS weight_sum
            FROM work_customer_preference_all_weeks GROUP BY 1
        )
        """,
        0.0,
        1e-10,
    ),
    Check(
        "no_history_sensitivity_weights_sum_to_one",
        """
        SELECT COALESCE(MAX(ABS(weight_sum - 1)), 0)
        FROM (
            SELECT household_key, SUM(preference_weight_top20) AS weight_sum
            FROM work_customer_preference_no_history_filter GROUP BY 1
        )
        """,
        0.0,
        1e-10,
    ),
    Check(
        "week_102_rows",
        """
        SELECT
            (SELECT COUNT(*) FROM mart_customer_week_exposure WHERE WEEK_NO = 102)
          + (SELECT COUNT(*) FROM mart_customer_week_panel WHERE WEEK_NO = 102)
        """,
        0.0,
    ),
    Check(
        "invalid_last_visit_rows",
        """
        SELECT COUNT(*)
        FROM mart_customer_week_panel
        WHERE last_visit_week IS NOT NULL
          AND last_visit_week >= WEEK_NO
        """,
        0.0,
    ),
    Check(
        "conflict_rows_counted_as_promotion",
        """
        SELECT COUNT(*)
        FROM work_relevant_promotion_clean
        WHERE promo_code_conflict = 1
          AND (is_feature_mailer <> 0 OR is_display <> 0
               OR is_coupon_mailer <> 0 OR is_free_mailer <> 0
               OR is_any_mailer <> 0)
        """,
        0.0,
    ),
    Check(
        "primary_response_row_count_difference",
        """
        SELECT ABS(
            (SELECT COUNT(*) FROM work_customer_response_base
             WHERE is_primary_analysis = 1)
            - 75 * (SELECT COUNT(*) FROM work_analysis_customer
                    WHERE is_primary_analysis = 1)
        )
        """,
        0.0,
    ),
    Check(
        "regression_any_feature_all_store_visit",
        """
        SELECT mean_visit_difference_pct_point
        FROM mart_within_customer_high_low
        WHERE exposure_type = 'any_feature'
        """,
        0.139176860531,
        1e-9,
    ),
    Check(
        "regression_any_feature_home_store_visit",
        """
        SELECT mean_home_store_visit_difference_pct_point
        FROM mart_within_customer_high_low
        WHERE exposure_type = 'any_feature'
        """,
        1.283939156644,
        1e-9,
    ),
    Check(
        "regression_any_feature_net_calendar_home_store_visit",
        """
        SELECT net_calendar_home_store_visit_difference_pct_point
        FROM mart_within_customer_high_low
        WHERE exposure_type = 'any_feature'
        """,
        0.706036760811,
        1e-9,
    ),
    Check(
        "regression_preferred_department_purchase",
        """
        SELECT mean_purchase_difference_pct_point
        FROM mart_department_within_response
        WHERE department_relation = 'preferred_top3'
        """,
        0.859206,
        1e-5,
    ),
]


def main() -> None:
    if not ANALYSIS_DB.is_file():
        raise FileNotFoundError(f"Analysis database not found: {ANALYSIS_DB}")

    failures: list[str] = []
    with duckdb.connect(str(ANALYSIS_DB), read_only=True) as con:
        print("check,status,value,expected,tolerance")
        for check in CHECKS:
            value = float(con.execute(check.sql).fetchone()[0])
            passed = abs(value - check.expected) <= check.tolerance
            status = "PASS" if passed else "FAIL"
            print(
                f"{check.name},{status},{value:.12g},"
                f"{check.expected:.12g},{check.tolerance:.12g}"
            )
            if not passed:
                failures.append(check.name)

    if failures:
        joined = ", ".join(failures)
        raise AssertionError(f"Customer-axis validation failed: {joined}")
    print(f"All {len(CHECKS)} validation checks passed.")


if __name__ == "__main__":
    main()
