"""Run the product-axis DuckDB SQL pipeline in filename order.

The source database is attached read-only. Intermediate tables and marts are
written to product_axis_outputs/product_axis.duckdb.
"""

from __future__ import annotations

import time
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parent
QUERY_DIR = ROOT / "queries" / "product_axis"
OUTPUT_DIR = ROOT / "product_axis_outputs"
SOURCE_DB = ROOT / "dunnhumby.duckdb"
ANALYSIS_DB = OUTPUT_DIR / "product_axis.duckdb"
TEMP_DIR = OUTPUT_DIR / "duckdb_tmp"

SQL_FILES = [QUERY_DIR / f"{number:02d}_{name}.sql" for number, name in (
    (0, "source_audit"),
    (1, "clean_promotion"),
    (2, "weekly_sales"),
    (3, "active_panel"),
    (4, "promo_2x2"),
    (5, "mailer_product_week"),
    (5, "within_pair_summary"),
    (6, "position_summary"),
    (7, "category_brand_summary"),
    (8, "weekly_event_trend"),
    (9, "category_promotion_priority"),
    (9, "export_marts"),
    (10, "export_category_promotion"),
)]


def sql_literal(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)

    missing = [path for path in SQL_FILES if not path.is_file()]
    if missing:
        joined = "\n".join(f"  - {path}" for path in missing)
        raise FileNotFoundError(f"Missing SQL files:\n{joined}")

    with duckdb.connect(str(ANALYSIS_DB)) as con:
        con.execute("SET threads = 4")
        con.execute("SET memory_limit = '8GB'")
        con.execute("SET preserve_insertion_order = false")
        con.execute(f"SET temp_directory = {sql_literal(TEMP_DIR)}")
        try:
            con.execute("DETACH source")
        except duckdb.Error:
            pass
        con.execute(
            f"ATTACH {sql_literal(SOURCE_DB)} AS source (READ_ONLY)"
        )

        total_start = time.perf_counter()
        for sql_path in SQL_FILES:
            started = time.perf_counter()
            print(f"[{sql_path.name}] running...", flush=True)
            con.execute(sql_path.read_text(encoding="utf-8"))
            elapsed = time.perf_counter() - started
            print(f"[{sql_path.name}] completed in {elapsed:,.1f}s", flush=True)

        elapsed = time.perf_counter() - total_start
        print(f"Pipeline completed in {elapsed:,.1f}s")
        print(f"Analysis database: {ANALYSIS_DB}")
        print(f"CSV outputs: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
