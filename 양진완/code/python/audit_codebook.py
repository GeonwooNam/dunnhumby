"""Read-only audit of codebook assumptions used by the product-axis analysis."""

from __future__ import annotations

from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "dunnhumby.duckdb"
ANALYSIS_DB_PATH = ROOT / "product_axis_outputs" / "product_axis.duckdb"


QUERIES = {
    "causal_code_combinations": """
        SELECT display, mailer, COUNT(*) AS rows
        FROM causal_data
        GROUP BY 1, 2
        ORDER BY 1, 2
    """,
    "causal_domain": """
        SELECT
            COUNT(*) AS rows,
            COUNT(*) FILTER (
                WHERE display IS NULL OR mailer IS NULL
            ) AS null_code_rows,
            COUNT(*) FILTER (
                WHERE display NOT IN ('0','1','2','3','4','5','6','7','9','A')
                   OR mailer NOT IN ('0','A','C','D','F','H','J','L','P','X','Z')
            ) AS unknown_code_rows,
            MIN(WEEK_NO) AS min_week,
            MAX(WEEK_NO) AS max_week,
            COUNT(DISTINCT STORE_ID) AS stores,
            COUNT(DISTINCT PRODUCT_ID) AS products
        FROM causal_data
    """,
    "explicit_none": """
        SELECT
            COUNT(*) FILTER (
                WHERE display = '0' AND mailer = '0'
            ) AS zero_zero_rows,
            COUNT(*) FILTER (
                WHERE display = 'A' AND mailer = '0'
            ) AS a_zero_rows,
            COUNT(*) FILTER (
                WHERE display IN ('0', 'A') AND mailer = '0'
            ) AS all_explicit_none_rows
        FROM causal_data
    """,
    "causal_key_quality": """
        WITH key_counts AS (
            SELECT
                PRODUCT_ID,
                STORE_ID,
                WEEK_NO,
                COUNT(*) AS rows,
                COUNT(DISTINCT display) AS display_codes,
                COUNT(DISTINCT mailer) AS mailer_codes
            FROM causal_data
            GROUP BY 1, 2, 3
        )
        SELECT
            COUNT(*) AS distinct_keys,
            SUM(rows - 1) AS duplicate_rows,
            COUNT(*) FILTER (WHERE rows > 1) AS duplicated_keys,
            COUNT(*) FILTER (
                WHERE display_codes > 1 OR mailer_codes > 1
            ) AS conflicting_keys
        FROM key_counts
    """,
    "causal_duplicate_patterns": """
        WITH duplicated AS (
            SELECT PRODUCT_ID, STORE_ID, WEEK_NO
            FROM causal_data
            GROUP BY 1, 2, 3
            HAVING COUNT(*) > 1
        )
        SELECT
            a.display AS display_1,
            a.mailer AS mailer_1,
            b.display AS display_2,
            b.mailer AS mailer_2,
            COUNT(*) AS key_pairs
        FROM duplicated AS d
        INNER JOIN causal_data AS a USING (PRODUCT_ID, STORE_ID, WEEK_NO)
        INNER JOIN causal_data AS b USING (PRODUCT_ID, STORE_ID, WEEK_NO)
        WHERE (a.display, a.mailer) < (b.display, b.mailer)
        GROUP BY 1, 2, 3, 4
        ORDER BY 5 DESC
        LIMIT 30
    """,
    "transaction_ranges": """
        SELECT
            COUNT(*) AS rows,
            MIN(WEEK_NO) AS min_week,
            MAX(WEEK_NO) AS max_week,
            MIN(DAY) AS min_day,
            MAX(DAY) AS max_day,
            COUNT(DISTINCT household_key) AS households,
            COUNT(DISTINCT STORE_ID) AS stores,
            MIN(QUANTITY) AS min_quantity,
            MAX(QUANTITY) AS max_quantity,
            MIN(SALES_VALUE) AS min_sales_value,
            MAX(SALES_VALUE) AS max_sales_value,
            MIN(RETAIL_DISC) AS min_retail_disc,
            MAX(RETAIL_DISC) AS max_retail_disc,
            MIN(COUPON_DISC) AS min_coupon_disc,
            MAX(COUPON_DISC) AS max_coupon_disc,
            MIN(COUPON_MATCH_DISC) AS min_coupon_match_disc,
            MAX(COUPON_MATCH_DISC) AS max_coupon_match_disc
        FROM transaction_data
    """,
    "transaction_signs": """
        SELECT
            COUNT(*) AS rows,
            COUNT(*) FILTER (WHERE QUANTITY < 0) AS negative_quantity_rows,
            COUNT(*) FILTER (WHERE QUANTITY = 0) AS zero_quantity_rows,
            COUNT(*) FILTER (WHERE SALES_VALUE < 0) AS negative_sales_rows,
            COUNT(*) FILTER (WHERE SALES_VALUE = 0) AS zero_sales_rows,
            COUNT(*) FILTER (WHERE RETAIL_DISC < 0) AS negative_retail_disc_rows,
            COUNT(*) FILTER (WHERE RETAIL_DISC > 0) AS positive_retail_disc_rows,
            COUNT(*) FILTER (WHERE COUPON_DISC < 0) AS negative_coupon_disc_rows,
            COUNT(*) FILTER (WHERE COUPON_DISC > 0) AS positive_coupon_disc_rows,
            COUNT(*) FILTER (
                WHERE COUPON_MATCH_DISC < 0
            ) AS negative_coupon_match_rows,
            COUNT(*) FILTER (
                WHERE COUPON_MATCH_DISC > 0
            ) AS positive_coupon_match_rows
        FROM transaction_data
    """,
    "zero_value_line_types": """
        SELECT
            COUNT(*) FILTER (
                WHERE QUANTITY = 0 AND SALES_VALUE = 0
            ) AS zero_quantity_and_sales_rows,
            COUNT(*) FILTER (
                WHERE QUANTITY = 0 AND SALES_VALUE > 0
            ) AS zero_quantity_positive_sales_rows,
            COUNT(*) FILTER (
                WHERE QUANTITY > 0 AND SALES_VALUE = 0
            ) AS positive_quantity_zero_sales_rows,
            COUNT(DISTINCT BASKET_ID) FILTER (
                WHERE QUANTITY = 0 AND SALES_VALUE = 0
            ) AS baskets_with_zero_lines,
            COUNT(DISTINCT PRODUCT_ID) FILTER (
                WHERE QUANTITY = 0 AND SALES_VALUE = 0
            ) AS products_with_zero_lines
        FROM transaction_data
    """,
    "transaction_time_consistency": """
        SELECT
            COUNT(*) FILTER (
                WHERE WEEK_NO <> CAST(FLOOR((DAY + 1) / 7.0) + 1 AS INTEGER)
            ) AS week_day_mismatches,
            COUNT(*) FILTER (
                WHERE TRY_STRPTIME(LPAD(TRANS_TIME, 4, '0'), '%H%M') IS NULL
            ) AS invalid_transaction_times
        FROM transaction_data
    """,
    "week_day_ranges": """
        SELECT WEEK_NO, MIN(DAY) AS min_day, MAX(DAY) AS max_day
        FROM transaction_data
        GROUP BY 1
        ORDER BY 1
        LIMIT 15
    """,
    "basket_key_quality": """
        WITH baskets AS (
            SELECT
                BASKET_ID,
                COUNT(DISTINCT household_key) AS households,
                COUNT(DISTINCT STORE_ID) AS stores,
                COUNT(DISTINCT WEEK_NO) AS weeks,
                COUNT(DISTINCT DAY) AS days
            FROM transaction_data
            GROUP BY 1
        )
        SELECT
            COUNT(*) AS baskets,
            COUNT(*) FILTER (
                WHERE households > 1 OR stores > 1 OR weeks > 1 OR days > 1
            ) AS conflicting_basket_keys
        FROM baskets
    """,
    "product_key_quality": """
        SELECT
            COUNT(*) AS rows,
            COUNT(DISTINCT PRODUCT_ID) AS product_ids,
            COUNT(*) FILTER (WHERE PRODUCT_ID IS NULL) AS null_product_ids,
            COUNT(*) FILTER (
                WHERE COMMODITY_DESC IS NULL
            ) AS null_commodity_rows
        FROM product
    """,
    "brand_domain": """
        SELECT BRAND, COUNT(*) AS rows
        FROM product
        GROUP BY 1
        ORDER BY 2 DESC
    """,
    "transaction_product_join": """
        SELECT
            COUNT(*) AS transaction_rows,
            COUNT(*) FILTER (
                WHERE p.PRODUCT_ID IS NULL
            ) AS unmatched_product_rows
        FROM transaction_data AS t
        LEFT JOIN product AS p USING (PRODUCT_ID)
    """,
}


ANALYSIS_QUERIES = {
    "promotion_clean_invariants": """
        SELECT
            COUNT(*) AS rows,
            COUNT(DISTINCT (PRODUCT_ID, STORE_ID, WEEK_NO)) AS distinct_keys,
            COUNT(*) FILTER (WHERE promo_code_conflict = 1) AS conflict_keys,
            COUNT(*) FILTER (WHERE is_explicit_none = 1) AS explicit_none_keys,
            COUNT(*) FILTER (WHERE display_code = 'A') AS in_shelf_as_display_rows,
            COUNT(*) FILTER (
                WHERE promo_group NOT IN (
                    'none','display_only','mailer_only','both','conflict'
                )
            ) AS unknown_group_rows
        FROM work_promotion_clean
    """,
    "active_panel_invariants": """
        SELECT
            COUNT(*) AS rows,
            COUNT(*) FILTER (
                WHERE promo_group = 'none' AND is_explicit_none <> 1
            ) AS invalid_none_rows,
            COUNT(*) FILTER (
                WHERE promo_group = 'unobserved'
                  AND promotion_record_present <> 0
            ) AS invalid_unobserved_rows,
            COUNT(*) FILTER (
                WHERE promo_group = 'conflict' AND promo_code_conflict <> 1
            ) AS invalid_conflict_rows
        FROM mart_product_store_week
    """,
}


def main() -> None:
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        for name, query in QUERIES.items():
            cursor = con.execute(query)
            headers = [column[0] for column in cursor.description]
            print(f"\n--- {name} ---")
            print("\t".join(headers))
            for row in cursor.fetchall():
                print("\t".join("NULL" if value is None else str(value) for value in row))

    if ANALYSIS_DB_PATH.exists():
        with duckdb.connect(str(ANALYSIS_DB_PATH), read_only=True) as con:
            for name, query in ANALYSIS_QUERIES.items():
                cursor = con.execute(query)
                headers = [column[0] for column in cursor.description]
                print(f"\n--- {name} ---")
                print("\t".join(headers))
                for row in cursor.fetchall():
                    print(
                        "\t".join(
                            "NULL" if value is None else str(value) for value in row
                        )
                    )


if __name__ == "__main__":
    main()
