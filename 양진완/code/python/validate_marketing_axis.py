"""Validate the marketing-axis cohort, funnel, and comparison outputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parent
ANALYSIS_DB = ROOT / "marketing_axis_outputs" / "marketing_axis.duckdb"


@dataclass
class Check:
    name: str
    sql: str
    expected: float
    tolerance: float = 0.0


CHECKS = [
    Check("high_value_households", "SELECT COUNT(*) FROM mart_marketing_risk_cohort", 403),
    Check(
        "published_returning_households",
        "SELECT COUNT(*) FROM mart_marketing_risk_cohort WHERE holdout_returned = 1",
        400,
    ),
    Check(
        "published_stage1_reproduction",
        "SELECT SUM(is_stage1_monitor) FROM mart_marketing_risk_cohort WHERE holdout_returned = 1",
        161,
    ),
    Check(
        "published_category_reproduction",
        "SELECT COUNT(*) FROM mart_marketing_risk_cohort WHERE holdout_returned = 1 AND category_ratio < 0.7",
        86,
    ),
    Check(
        "published_stage2_reproduction",
        "SELECT SUM(is_stage2_target) FROM mart_marketing_risk_cohort WHERE holdout_returned = 1",
        65,
    ),
    Check(
        "future_safe_stage2_households",
        "SELECT SUM(is_stage2_target) FROM mart_marketing_risk_cohort",
        67,
    ),
    Check(
        "stage2_duplicate_households",
        "SELECT COUNT(*) - COUNT(DISTINCT household_key) FROM work_marketing_stage2_status",
        0,
    ),
    Check(
        "campaign_assigned_4week",
        "SELECT SUM(campaign_assigned_4week) FROM work_marketing_stage2_status",
        57,
    ),
    Check(
        "campaign_assigned_8week",
        "SELECT SUM(campaign_assigned_8week) FROM work_marketing_stage2_status",
        58,
    ),
    Check(
        "coupon_redeemed_4week",
        "SELECT SUM(coupon_redeemed_4week) FROM work_marketing_stage2_status",
        1,
    ),
    Check(
        "coupon_redeemed_8week",
        "SELECT SUM(coupon_redeemed_8week) FROM work_marketing_stage2_status",
        7,
    ),
    Check(
        "campaign18_assigned",
        "SELECT SUM(campaign18_assigned) FROM work_marketing_stage2_status",
        56,
    ),
    Check(
        "campaign18_unassigned",
        "SELECT COUNT(*) FROM work_marketing_stage2_status WHERE campaign18_assigned = 0",
        11,
    ),
    Check(
        "campaign18_redeemed",
        "SELECT SUM(campaign18_redeemed) FROM work_marketing_stage2_status",
        7,
    ),
    Check(
        "campaign18_comparison_households",
        "SELECT COUNT(*) FROM work_campaign18_customer_metric",
        67,
    ),
    Check(
        "common_support_strata_min",
        "SELECT MIN(common_support_strata) FROM mart_campaign18_adjusted_difference",
        3,
    ),
    Check(
        "common_support_households_min",
        "SELECT MIN(common_support_households) FROM mart_campaign18_adjusted_difference",
        67,
    ),
    Check(
        "stratified_sales_retention_56",
        "SELECT stratified_difference FROM mart_campaign18_adjusted_difference WHERE metric = 'sales_retention_56'",
        -0.0010049078911479187,
        1e-12,
    ),
    Check(
        "stratified_category_recovery_56",
        "SELECT stratified_difference FROM mart_campaign18_adjusted_difference WHERE metric = 'category_recovery_56'",
        0.07610298396729342,
        1e-12,
    ),
    Check(
        "stratified_visit_days_56",
        "SELECT stratified_difference FROM mart_campaign18_adjusted_difference WHERE metric = 'visit_days_56'",
        -0.7376931133804661,
        1e-12,
    ),
]


def main() -> None:
    if not ANALYSIS_DB.is_file():
        raise FileNotFoundError(f"Run run_marketing_axis.py first: {ANALYSIS_DB}")

    failures: list[str] = []
    with duckdb.connect(str(ANALYSIS_DB), read_only=True) as con:
        for check in CHECKS:
            actual = con.execute(check.sql).fetchone()[0]
            passed = abs(float(actual) - check.expected) <= check.tolerance
            print(f"{'PASS' if passed else 'FAIL'} {check.name}: {actual}")
            if not passed:
                failures.append(
                    f"{check.name}: expected {check.expected}, got {actual}"
                )

    if failures:
        raise AssertionError("Validation failures:\n" + "\n".join(failures))
    print(f"All {len(CHECKS)} checks passed.")


if __name__ == "__main__":
    main()
