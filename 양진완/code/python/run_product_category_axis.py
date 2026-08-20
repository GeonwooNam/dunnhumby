"""Run only the category-promotion extension on the existing product-axis DB."""

from __future__ import annotations

import time
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parent
QUERY_DIR = ROOT / "queries" / "product_axis"
OUTPUT_DIR = ROOT / "product_axis_outputs"
SOURCE_DB = ROOT / "dunnhumby.duckdb"
ANALYSIS_DB = OUTPUT_DIR / "product_axis.duckdb"
SQL_FILES = [
    QUERY_DIR / "09_category_promotion_priority.sql",
    QUERY_DIR / "10_export_category_promotion.sql",
]


def sql_literal(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def main() -> None:
    if not ANALYSIS_DB.is_file():
        raise FileNotFoundError(
            "product_axis.duckdb가 없습니다. 먼저 python run_product_axis.py를 실행하세요."
        )

    with duckdb.connect(str(ANALYSIS_DB)) as con:
        con.execute("SET threads = 4")
        try:
            con.execute("DETACH source")
        except duckdb.Error:
            pass
        con.execute(f"ATTACH {sql_literal(SOURCE_DB)} AS source (READ_ONLY)")

        started = time.perf_counter()
        for sql_path in SQL_FILES:
            print(f"[{sql_path.name}] running...", flush=True)
            con.execute(sql_path.read_text(encoding="utf-8"))
            print(f"[{sql_path.name}] completed", flush=True)

        elapsed = time.perf_counter() - started
        print(f"Category extension completed in {elapsed:,.1f}s")


if __name__ == "__main__":
    main()
