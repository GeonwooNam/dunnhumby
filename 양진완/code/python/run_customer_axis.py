"""Run the customer-axis DuckDB SQL pipeline in analysis order.

The source database is attached read-only. Intermediate tables and marts are
written to customer_axis_outputs/customer_axis.duckdb.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parent
QUERY_DIR = ROOT / "queries" / "customer_axis"
OUTPUT_DIR = ROOT / "customer_axis_outputs"
SOURCE_DB = ROOT / "dunnhumby.duckdb"
ANALYSIS_DB = OUTPUT_DIR / "customer_axis.duckdb"
TEMP_DIR = OUTPUT_DIR / "duckdb_tmp"

SQL_FILES = [
    QUERY_DIR / "00_customer_source_audit.sql",
    QUERY_DIR / "01_baseline_customer.sql",
    QUERY_DIR / "02_home_store_preferences.sql",
    QUERY_DIR / "03_promotion_exposure.sql",
    QUERY_DIR / "04_customer_week_panel.sql",
    QUERY_DIR / "05_within_customer_response.sql",
    QUERY_DIR / "06_export_customer_marts.sql",
]


def sql_literal(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)
    os.chdir(ROOT)

    missing = [path for path in SQL_FILES if not path.is_file()]
    if missing:
        joined = "\n".join(f"  - {path}" for path in missing)
        raise FileNotFoundError(f"Missing SQL files:\n{joined}")

    # 분석 DB는 재실행 때마다 새로 만들어 이전 실행의 테이블·행이 섞이지
    # 않게 한다. 원본 DB와 CSV 입력은 건드리지 않는다.
    if ANALYSIS_DB.exists():
        ANALYSIS_DB.unlink()

    with duckdb.connect(str(ANALYSIS_DB)) as con:
        # 부동소수점 집계 순서까지 고정해 결과 CSV가 재실행마다 같도록 한다.
        con.execute("SET threads = 1")
        con.execute("SET memory_limit = '8GB'")
        con.execute("SET preserve_insertion_order = false")
        con.execute(f"SET temp_directory = {sql_literal(TEMP_DIR)}")
        try:
            con.execute("DETACH source")
        except duckdb.Error:
            pass
        con.execute(f"ATTACH {sql_literal(SOURCE_DB)} AS source (READ_ONLY)")

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
