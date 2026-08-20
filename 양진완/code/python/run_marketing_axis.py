"""Run the DuckDB marketing reach and post-campaign outcome pipeline."""

from __future__ import annotations

import os
import time
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parent
QUERY_DIR = ROOT / "queries" / "marketing_axis"
OUTPUT_DIR = ROOT / "marketing_axis_outputs"
SOURCE_DB = ROOT / "dunnhumby.duckdb"
ANALYSIS_DB = OUTPUT_DIR / "marketing_axis.duckdb"
TEMP_DIR = OUTPUT_DIR / "duckdb_tmp"

SQL_FILES = [
    QUERY_DIR / "00_risk_cohort.sql",
    QUERY_DIR / "01_reach_funnel.sql",
    QUERY_DIR / "02_outcome_association.sql",
    QUERY_DIR / "03_export_marts.sql",
]


def sql_literal(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)
    os.chdir(ROOT)

    missing = [path for path in SQL_FILES if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing SQL files:\n" + "\n".join(map(str, missing)))

    if ANALYSIS_DB.exists():
        ANALYSIS_DB.unlink()

    with duckdb.connect(str(ANALYSIS_DB)) as con:
        con.execute("SET threads = 1")
        con.execute("SET memory_limit = '8GB'")
        con.execute("SET preserve_insertion_order = false")
        con.execute(f"SET temp_directory = {sql_literal(TEMP_DIR)}")
        con.execute(f"ATTACH {sql_literal(SOURCE_DB)} AS source (READ_ONLY)")

        started_all = time.perf_counter()
        for sql_path in SQL_FILES:
            started = time.perf_counter()
            print(f"[{sql_path.name}] running...", flush=True)
            con.execute(sql_path.read_text(encoding="utf-8"))
            print(
                f"[{sql_path.name}] completed in "
                f"{time.perf_counter() - started:,.1f}s",
                flush=True,
            )

        print(f"Pipeline completed in {time.perf_counter() - started_all:,.1f}s")
        print(f"Analysis database: {ANALYSIS_DB}")


if __name__ == "__main__":
    main()

