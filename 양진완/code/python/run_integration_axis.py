"""Build product-response profiles and customer-product strategy marts."""

from __future__ import annotations

import os
import time
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parent
QUERY_DIR = ROOT / "queries" / "integration_axis"
OUTPUT_DIR = ROOT / "integration_axis_outputs"
ANALYSIS_DB = OUTPUT_DIR / "integration_axis.duckdb"
TEMP_DIR = OUTPUT_DIR / "duckdb_tmp"
PRODUCT_DB = ROOT / "product_axis_outputs" / "product_axis.duckdb"
CUSTOMER_DB = ROOT / "customer_axis_outputs" / "customer_axis.duckdb"
SOURCE_DB = ROOT / "dunnhumby.duckdb"

SQL_FILES = [
    QUERY_DIR / "00_product_response_profile.sql",
    QUERY_DIR / "01_customer_product_fit.sql",
    QUERY_DIR / "02_export_marts.sql",
]


def sql_literal(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)
    os.chdir(ROOT)

    dependencies = [PRODUCT_DB, CUSTOMER_DB, SOURCE_DB, *SQL_FILES]
    missing = [path for path in dependencies if not path.is_file()]
    if missing:
        joined = "\n".join(f"  - {path}" for path in missing)
        raise FileNotFoundError(f"Missing integration dependencies:\n{joined}")

    if ANALYSIS_DB.exists():
        ANALYSIS_DB.unlink()

    with duckdb.connect(str(ANALYSIS_DB)) as con:
        con.execute("SET threads = 1")
        con.execute("SET memory_limit = '8GB'")
        con.execute("SET preserve_insertion_order = false")
        con.execute(f"SET temp_directory = {sql_literal(TEMP_DIR)}")
        con.execute(
            f"ATTACH {sql_literal(PRODUCT_DB)} AS product_axis (READ_ONLY)"
        )
        con.execute(
            f"ATTACH {sql_literal(CUSTOMER_DB)} AS customer_axis (READ_ONLY)"
        )
        con.execute(f"ATTACH {sql_literal(SOURCE_DB)} AS source (READ_ONLY)")

        total_start = time.perf_counter()
        for sql_path in SQL_FILES:
            started = time.perf_counter()
            print(f"[{sql_path.name}] running...", flush=True)
            con.execute(sql_path.read_text(encoding="utf-8"))
            elapsed = time.perf_counter() - started
            print(f"[{sql_path.name}] completed in {elapsed:,.1f}s", flush=True)

        elapsed = time.perf_counter() - total_start
        print(f"Integration pipeline completed in {elapsed:,.1f}s")
        print(f"Analysis database: {ANALYSIS_DB}")
        print(f"CSV outputs: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
