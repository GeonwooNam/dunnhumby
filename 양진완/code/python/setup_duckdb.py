"""Build and validate a local DuckDB copy of The Complete Journey CSV files.

Source CSV files live in ``data/`` and are read directly by DuckDB; they are
never loaded into pandas or modified.  For safety, this script refuses to
overwrite an existing database.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = PROJECT_ROOT / "dunnhumby.duckdb"
REPORT_PATH = PROJECT_ROOT / "duckdb_validation.md"

EXPECTED_FILES = (
    "transaction_data.csv",
    "product.csv",
    "hh_demographic.csv",
    "campaign_desc.csv",
    "campaign_table.csv",
    "coupon.csv",
    "coupon_redempt.csv",
    "causal_data.csv",
)

# These overrides prevent identifier overflow and mixed-value inference errors.
# Other columns continue to use DuckDB's automatic schema detection.
TYPE_OVERRIDES: dict[str, dict[str, str]] = {
    "transaction_data.csv": {
        "household_key": "BIGINT",
        "BASKET_ID": "BIGINT",
        "PRODUCT_ID": "BIGINT",
        "STORE_ID": "BIGINT",
        "TRANS_TIME": "VARCHAR",
    },
    "product.csv": {"PRODUCT_ID": "BIGINT"},
    "hh_demographic.csv": {"household_key": "BIGINT"},
    "campaign_table.csv": {"household_key": "BIGINT"},
    "coupon.csv": {"COUPON_UPC": "BIGINT", "PRODUCT_ID": "BIGINT"},
    "coupon_redempt.csv": {
        "household_key": "BIGINT",
        "COUPON_UPC": "BIGINT",
    },
    "causal_data.csv": {
        "PRODUCT_ID": "BIGINT",
        "STORE_ID": "BIGINT",
        "display": "VARCHAR",
        "mailer": "VARCHAR",
    },
}

ANALYSIS_QUERY = """
SELECT
    p.DEPARTMENT,
    ROUND(SUM(t.SALES_VALUE), 2) AS total_sales,
    SUM(t.QUANTITY) AS total_quantity,
    COUNT(DISTINCT t.BASKET_ID) AS order_count
FROM transaction_data AS t
JOIN product AS p
    ON t.PRODUCT_ID = p.PRODUCT_ID
GROUP BY p.DEPARTMENT
ORDER BY total_sales DESC
LIMIT 10;
""".strip()


def quote_identifier(value: str) -> str:
    """Return a safely quoted DuckDB identifier."""
    return '"' + value.replace('"', '""') + '"'


def sql_string(value: str) -> str:
    """Return a safely quoted SQL string literal."""
    return "'" + value.replace("'", "''") + "'"


def type_map_sql(overrides: dict[str, str]) -> str:
    entries = ", ".join(
        f"{sql_string(column)}: {sql_string(data_type)}"
        for column, data_type in overrides.items()
    )
    return "{" + entries + "}"


def discover_csv_files(root: Path) -> dict[str, Path]:
    """Find each expected CSV recursively and reject missing/duplicate matches."""
    if not root.is_dir():
        raise RuntimeError(f"CSV data directory does not exist: {root}")
    csv_paths = [path for path in root.rglob("*.csv") if path.is_file()]
    discovered: dict[str, Path] = {}
    problems: list[str] = []

    for expected in EXPECTED_FILES:
        matches = [
            path for path in csv_paths if path.name.casefold() == expected.casefold()
        ]
        if not matches:
            problems.append(f"missing: {expected}")
        elif len(matches) > 1:
            joined = ", ".join(str(path) for path in matches)
            problems.append(f"duplicate: {expected} -> {joined}")
        else:
            discovered[expected] = matches[0]

    if problems:
        raise RuntimeError("CSV discovery failed:\n  - " + "\n  - ".join(problems))
    return discovered


def inspect_existing_database(path: Path) -> None:
    """Print an existing database's state without modifying it."""
    print(f"Existing database found; no changes will be made: {path}")
    try:
        with duckdb.connect(str(path), read_only=True) as connection:
            tables = [row[0] for row in connection.execute("SHOW TABLES").fetchall()]
            if not tables:
                print("Existing database has no tables.")
                return
            print("Existing tables:")
            for table in tables:
                try:
                    count = connection.execute(
                        f"SELECT COUNT(*) FROM {quote_identifier(table)}"
                    ).fetchone()[0]
                    print(f"  - {table}: {count:,} rows")
                except Exception as exc:  # Keep inspecting other tables.
                    print(f"  - {table}: row count failed ({exc})")
    except Exception as exc:
        print(f"Could not open the existing file as DuckDB: {exc}", file=sys.stderr)


def create_table(
    connection: duckdb.DuckDBPyConnection,
    table: str,
    csv_path: Path,
    overrides: dict[str, str],
) -> int:
    """Stream one CSV into a physical DuckDB table and return its row count."""
    table_sql = quote_identifier(table)
    types_clause = (
        f",\n            types = {type_map_sql(overrides)}" if overrides else ""
    )
    query = f"""
        CREATE TABLE {table_sql} AS
        SELECT *
        FROM read_csv(
            ?,
            header = true,
            auto_detect = true,
            sample_size = 20480{types_clause}
        )
    """
    connection.execute(query, [str(csv_path)])
    return connection.execute(f"SELECT COUNT(*) FROM {table_sql}").fetchone()[0]


def fetch_validation(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[
    list[str],
    dict[str, int],
    dict[str, list[tuple[Any, ...]]],
    int,
    list[str],
    list[tuple[Any, ...]],
    dict[str, tuple[Any, Any]],
]:
    """Run all required table, schema, identifier, and JOIN checks."""
    tables = [row[0] for row in connection.execute("SHOW TABLES").fetchall()]
    expected_tables = [Path(name).stem for name in EXPECTED_FILES]
    missing_tables = [table for table in expected_tables if table not in tables]

    row_counts: dict[str, int] = {}
    schemas: dict[str, list[tuple[Any, ...]]] = {}
    for table in expected_tables:
        if table not in tables:
            continue
        table_sql = quote_identifier(table)
        row_counts[table] = connection.execute(
            f"SELECT COUNT(*) FROM {table_sql}"
        ).fetchone()[0]
        schemas[table] = connection.execute(
            f"DESCRIBE SELECT * FROM {table_sql}"
        ).fetchall()

    join_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM transaction_data AS t
        JOIN product AS p ON t.PRODUCT_ID = p.PRODUCT_ID
        """
    ).fetchone()[0]

    analysis_cursor = connection.execute(ANALYSIS_QUERY)
    analysis_columns = [item[0] for item in analysis_cursor.description]
    analysis_rows = analysis_cursor.fetchall()

    identifier_ranges: dict[str, tuple[Any, Any]] = {}
    range_checks = {
        "transaction_data.BASKET_ID": ("transaction_data", "BASKET_ID"),
        "transaction_data.PRODUCT_ID": ("transaction_data", "PRODUCT_ID"),
        "product.PRODUCT_ID": ("product", "PRODUCT_ID"),
        "coupon.COUPON_UPC": ("coupon", "COUPON_UPC"),
        "coupon_redempt.COUPON_UPC": ("coupon_redempt", "COUPON_UPC"),
        "transaction_data.household_key": ("transaction_data", "household_key"),
    }
    for label, (table, column) in range_checks.items():
        identifier_ranges[label] = connection.execute(
            f"SELECT MIN({quote_identifier(column)}), MAX({quote_identifier(column)}) "
            f"FROM {quote_identifier(table)}"
        ).fetchone()

    return (
        tables,
        row_counts,
        schemas,
        join_count,
        missing_tables,
        analysis_rows,
        identifier_ranges,
    ), analysis_columns


def markdown_cell(value: Any) -> str:
    if value is None:
        return "NULL"
    return str(value).replace("|", "\\|").replace("\n", " ")


def markdown_table(headers: list[str], rows: list[tuple[Any, ...]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(markdown_cell(value) for value in row) + " |"
        for row in rows
    )
    return "\n".join(lines)


def write_report(
    csv_files: dict[str, Path],
    tables: list[str],
    row_counts: dict[str, int],
    schemas: dict[str, list[tuple[Any, ...]]],
    join_count: int,
    missing_tables: list[str],
    analysis_columns: list[str],
    analysis_rows: list[tuple[Any, ...]],
    identifier_ranges: dict[str, tuple[Any, Any]],
) -> None:
    expected_tables = [Path(name).stem for name in EXPECTED_FILES]
    unexpected_tables = [table for table in tables if table not in expected_tables]
    all_present = not missing_tables

    lines = [
        "# Dunnhumby DuckDB 적재 및 검증 결과",
        "",
        f"- 검증 시각: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- 데이터베이스 경로: `{DATABASE_PATH}`",
        f"- DuckDB 버전: `{duckdb.__version__}`",
        f"- 예상한 8개 테이블 모두 존재: `{'예' if all_present else '아니요'}`",
        f"- 누락 테이블: `{', '.join(missing_tables) if missing_tables else '없음'}`",
        f"- 예상 외 테이블: `{', '.join(unexpected_tables) if unexpected_tables else '없음'}`",
        "",
        "## 원본 CSV",
        "",
        markdown_table(
            ["파일", "상대 경로", "크기(bytes)"],
            [
                (
                    filename,
                    csv_files[filename].relative_to(PROJECT_ROOT),
                    csv_files[filename].stat().st_size,
                )
                for filename in EXPECTED_FILES
            ],
        ),
        "",
        "## 테이블별 행 수",
        "",
        markdown_table(
            ["테이블", "행 수"],
            [(table, row_counts.get(table, "누락")) for table in expected_tables],
        ),
        "",
        "## 컬럼 타입 (`DESCRIBE`)",
        "",
    ]

    describe_headers = ["column_name", "column_type", "null", "key", "default", "extra"]
    for table in expected_tables:
        lines.extend(
            [
                f"### `{table}`",
                "",
                markdown_table(describe_headers, schemas.get(table, [])),
                "",
            ]
        )

    lines.extend(
        [
            "## 식별자 타입 및 값 범위 확인",
            "",
            "식별자는 CSV 파싱 시 `BIGINT`로 고정했습니다. `display`, `mailer`, "
            "`TRANS_TIME`은 혼합값 또는 표기 보존을 위해 `VARCHAR`로 고정했습니다.",
            "",
            markdown_table(
                ["컬럼", "최솟값", "최댓값"],
                [
                    (label, bounds[0], bounds[1])
                    for label, bounds in identifier_ranges.items()
                ],
            ),
            "",
            "## 적재 중 발견한 문제",
            "",
            "- 최종 적재 실행에서는 CSV 파싱 또는 데이터 적재 오류가 발생하지 않았습니다.",
            "- 최초 개발 실행에서는 타입 오버라이드가 없는 파일에 빈 `types = {}`를 "
            "전달해 DuckDB 구문 오류가 발생했습니다. 전체 트랜잭션이 롤백되고 테이블이 "
            "0개임을 확인한 뒤, 이번 작업에서 생성된 빈 DB만 제거하고 해당 인자를 "
            "생략하도록 스크립트를 수정했습니다.",
            "- `causal_data.display`에는 숫자 코드와 `A`가, `mailer`에는 숫자 코드와 "
            "문자 코드가 함께 있어 두 컬럼을 `VARCHAR`로 적재했습니다.",
            "- 자동 타입 추론만 사용할 때의 범위·혼합형 위험을 피하기 위해 위 컬럼에만 "
            "명시적 타입 오버라이드를 적용했습니다. 원본 값의 전처리나 임의 변경은 하지 않았습니다.",
            "",
            "## JOIN 검증",
            "",
            "`transaction_data.PRODUCT_ID = product.PRODUCT_ID` INNER JOIN 결과:",
            "",
            f"- 조인된 행 수: `{join_count}`",
            "",
            "## 예시 분석 쿼리",
            "",
            "```sql",
            ANALYSIS_QUERY,
            "```",
            "",
            "실행 결과:",
            "",
            markdown_table(analysis_columns, analysis_rows),
            "",
            "## 읽기 전용 Python 접속",
            "",
            "프로젝트 루트에서 다음과 같이 접속할 수 있습니다.",
            "",
            "```python",
            "import duckdb",
            "",
            'con = duckdb.connect("dunnhumby.duckdb", read_only=True)',
            "```",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    print(f"Project root: {PROJECT_ROOT}")
    print(f"CSV data directory: {DATA_DIR}")
    print(f"DuckDB target: {DATABASE_PATH}")

    if DATABASE_PATH.exists():
        inspect_existing_database(DATABASE_PATH)
        print(
            "Refusing to overwrite the existing database. Decide whether to keep, "
            "rename, back up, or remove it before running this script again.",
            file=sys.stderr,
        )
        return 2

    try:
        csv_files = discover_csv_files(DATA_DIR)
    except Exception as exc:
        print(f"ERROR during CSV discovery: {exc}", file=sys.stderr)
        return 1

    print("Discovered CSV files:")
    for filename in EXPECTED_FILES:
        path = csv_files[filename]
        print(f"  - {filename}: {path} ({path.stat().st_size:,} bytes)")

    connection: duckdb.DuckDBPyConnection | None = None
    load_started = time.perf_counter()
    active_file = ""
    active_table = ""
    try:
        connection = duckdb.connect(str(DATABASE_PATH))
        connection.execute("SET preserve_insertion_order = false")
        connection.execute("BEGIN TRANSACTION")

        for filename in EXPECTED_FILES:
            active_file = filename
            active_table = Path(filename).stem
            path = csv_files[filename]
            started = time.perf_counter()
            print(
                f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
                f"START file={path} table={active_table}",
                flush=True,
            )
            row_count = create_table(
                connection,
                active_table,
                path,
                TYPE_OVERRIDES.get(filename, {}),
            )
            elapsed = time.perf_counter() - started
            print(
                f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
                f"DONE  file={path} table={active_table} "
                f"rows={row_count:,} elapsed={elapsed:.2f}s",
                flush=True,
            )

        connection.execute("COMMIT")
        total_elapsed = time.perf_counter() - load_started
        print(f"All tables loaded in {total_elapsed:.2f}s. Starting validation.")

        validation, analysis_columns = fetch_validation(connection)
        (
            tables,
            row_counts,
            schemas,
            join_count,
            missing_tables,
            analysis_rows,
            identifier_ranges,
        ) = validation

        if missing_tables:
            raise RuntimeError(f"Expected tables are missing: {missing_tables}")

        write_report(
            csv_files,
            tables,
            row_counts,
            schemas,
            join_count,
            missing_tables,
            analysis_columns,
            analysis_rows,
            identifier_ranges,
        )

        print(f"SHOW TABLES: {', '.join(tables)}")
        for table in [Path(name).stem for name in EXPECTED_FILES]:
            print(f"  - {table}: {row_counts[table]:,} rows")
        print(f"JOIN matched rows: {join_count:,}")
        print("Example analysis query result:")
        print(markdown_table(analysis_columns, analysis_rows))
        print(f"Validation report written: {REPORT_PATH}")
        return 0
    except Exception as exc:
        if connection is not None:
            try:
                connection.execute("ROLLBACK")
            except Exception:
                pass
        location = (
            f" file={csv_files.get(active_file, active_file)} table={active_table}"
            if active_file
            else ""
        )
        print(f"ERROR{location}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
