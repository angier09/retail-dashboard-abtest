"""Export RetailPulse dbt marts into Tableau-ready files.

This script reads the local DuckDB database produced by dbt and writes curated
CSV and Parquet extracts for Tableau. It exports both the core mart tables and
a denormalized sales dataset that is convenient for drag-and-drop BI analysis.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb


DEFAULT_DATABASE_PATH = Path(
    os.getenv("RETAILPULSE_DUCKDB_PATH", "retailpulse.duckdb")
)
DEFAULT_EXPORT_DIR = Path(
    os.getenv("RETAILPULSE_TABLEAU_EXPORT_DIR", "tableau/exports")
)
DEFAULT_FORMATS = ("csv", "parquet")
SUPPORTED_FORMATS = {"csv", "parquet"}
@dataclass(frozen=True)
class ExportSpec:
    """Configuration for one Tableau export.

    Attributes:
        name: File stem used for exported artifacts.
        description: Human-readable dataset description for the manifest.
        query: SQL query that returns the exported dataset.
    """

    name: str
    description: str
    query: str


@dataclass(frozen=True)
class ExportResult:
    """Metadata for one exported file.

    Attributes:
        dataset_name: Logical export dataset name.
        file_format: Exported file format.
        path: Output file path.
        row_count: Number of rows written.
    """

    dataset_name: str
    file_format: str
    path: Path
    row_count: int


@dataclass(frozen=True)
class ExportManifest:
    """Manifest describing a Tableau export run.

    Attributes:
        generated_at: UTC timestamp for the export run.
        database_path: DuckDB database used as the source.
        export_dir: Directory containing exported files.
        results: File-level export metadata.
    """

    generated_at: str
    database_path: Path
    export_dir: Path
    results: tuple[ExportResult, ...]


TABLEAU_SALES_DATASET_QUERY = """
select
    sales.sales_line_item_id,
    sales.order_id,
    sales.order_item_id,
    sales.order_purchase_date,
    sales.customer_unique_id,
    customers.customer_state,
    customers.customer_city,
    customers.rfm_segment,
    customers.rfm_score,
    customers.recency_days,
    customers.order_count as customer_order_count,
    customers.gross_value as customer_lifetime_gross_value,
    customers.is_churned,
    sales.product_id,
    products.product_category_name_english,
    products.product_weight_g,
    products.product_length_cm,
    products.product_height_cm,
    products.product_width_cm,
    sales.seller_id,
    sellers.seller_state,
    sellers.seller_city,
    sales.primary_payment_type,
    sales.item_price,
    sales.freight_value,
    sales.item_total_value,
    sales.has_valid_delivery_timing,
    sales.delivery_days,
    sales.delivery_delay_days,
    sales.latest_review_score
from main_marts.fct_sales as sales
left join main_marts.dim_customer as customers
    on sales.customer_unique_id = customers.customer_unique_id
left join main_marts.dim_product as products
    on sales.product_id = products.product_id
left join main_marts.dim_seller as sellers
    on sales.seller_id = sellers.seller_id
"""
MART_EXPORTS: tuple[ExportSpec, ...] = (
    ExportSpec(
        name="tableau_sales_dataset",
        description="Wide delivered sales line-item dataset for Tableau.",
        query=TABLEAU_SALES_DATASET_QUERY,
    ),
    ExportSpec(
        name="fct_sales",
        description="Delivered order item fact table.",
        query="select * from main_marts.fct_sales",
    ),
    ExportSpec(
        name="fct_orders",
        description="Order-grain fact table with sales and delivery KPIs.",
        query="select * from main_marts.fct_orders",
    ),
    ExportSpec(
        name="dim_customer",
        description="Customer dimension with RFM segments and churn flag.",
        query="select * from main_marts.dim_customer",
    ),
    ExportSpec(
        name="dim_product",
        description="Product dimension with sales rollups.",
        query="select * from main_marts.dim_product",
    ),
    ExportSpec(
        name="dim_seller",
        description="Seller dimension with sales rollups.",
        query="select * from main_marts.dim_seller",
    ),
    ExportSpec(
        name="agg_daily_sales",
        description="Daily KPI aggregate for dashboard trend analysis.",
        query="select * from main_marts.agg_daily_sales",
    ),
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the Tableau exporter.

    Returns:
        Parsed command-line arguments.
    """

    parser = argparse.ArgumentParser(
        description="Export RetailPulse mart tables for Tableau."
    )
    parser.add_argument(
        "--database-path",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help="Path to the DuckDB database produced by dbt.",
    )
    parser.add_argument(
        "--export-dir",
        type=Path,
        default=DEFAULT_EXPORT_DIR,
        help="Directory where Tableau export files should be written.",
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        default=list(DEFAULT_FORMATS),
        choices=sorted(SUPPORTED_FORMATS),
        help="One or more export formats to write.",
    )
    return parser.parse_args()


def validate_database(database_path: Path) -> None:
    """Validate that the DuckDB database exists and contains mart tables.

    Args:
        database_path: Path to the DuckDB database file.

    Raises:
        FileNotFoundError: If the database file is missing.
        ValueError: If one or more required mart tables are absent.
    """

    if not database_path.exists():
        raise FileNotFoundError(
            f"DuckDB database not found at {database_path}. Run dbt first."
        )

    required_tables = {
        "main_marts.fct_sales",
        "main_marts.fct_orders",
        "main_marts.dim_customer",
        "main_marts.dim_product",
        "main_marts.dim_seller",
        "main_marts.agg_daily_sales",
    }
    with duckdb.connect(str(database_path), read_only=True) as connection:
        available_tables = {
            f"{schema_name}.{table_name}"
            for schema_name, table_name in connection.execute(
                """
                select table_schema, table_name
                from information_schema.tables
                where table_schema = 'main_marts'
                """
            ).fetchall()
        }

    missing_tables = sorted(required_tables.difference(available_tables))
    if missing_tables:
        formatted_tables = ", ".join(missing_tables)
        raise ValueError(
            f"Required mart tables are missing: {formatted_tables}. "
            "Run `dbt run --project-dir dbt --profiles-dir dbt` first."
        )


def validate_formats(file_formats: list[str]) -> tuple[str, ...]:
    """Validate requested file formats.

    Args:
        file_formats: Formats requested by the caller.

    Returns:
        Deduplicated tuple of validated formats.

    Raises:
        ValueError: If no formats or unsupported formats are supplied.
    """

    normalized_formats = tuple(dict.fromkeys(file_formats))
    if not normalized_formats:
        raise ValueError("At least one export format is required.")

    unsupported_formats = sorted(
        set(normalized_formats).difference(SUPPORTED_FORMATS)
    )
    if unsupported_formats:
        formatted_formats = ", ".join(unsupported_formats)
        raise ValueError(f"Unsupported export formats: {formatted_formats}")
    return normalized_formats


def export_dataset(
    connection: duckdb.DuckDBPyConnection,
    export_spec: ExportSpec,
    export_dir: Path,
    file_format: str,
) -> ExportResult:
    """Export one dataset in one file format.

    Args:
        connection: Open DuckDB connection.
        export_spec: Dataset export configuration.
        export_dir: Directory where the export file should be written.
        file_format: File format to write.

    Returns:
        Metadata describing the exported file.
    """

    row_count = count_rows(connection, export_spec.query)
    output_path = export_dir / f"{export_spec.name}.{file_format}"

    if file_format == "csv":
        copy_sql = (
            f"copy ({export_spec.query}) to '{escape_path(output_path)}' "
            "(header, delimiter ',')"
        )
    else:
        copy_sql = (
            f"copy ({export_spec.query}) to '{escape_path(output_path)}' "
            "(format parquet)"
        )

    connection.execute(copy_sql)
    return ExportResult(
        dataset_name=export_spec.name,
        file_format=file_format,
        path=output_path,
        row_count=row_count,
    )


def count_rows(
    connection: duckdb.DuckDBPyConnection,
    query: str,
) -> int:
    """Count rows returned by a query.

    Args:
        connection: Open DuckDB connection.
        query: SQL query to count.

    Returns:
        Number of rows returned by the query.
    """

    return int(connection.execute(f"select count(*) from ({query})").fetchone()[0])


def escape_path(path: Path) -> str:
    """Escape a filesystem path for use inside DuckDB COPY SQL.

    Args:
        path: Output filesystem path.

    Returns:
        POSIX path string with single quotes escaped.
    """

    return path.as_posix().replace("'", "''")


def write_manifest(manifest: ExportManifest) -> Path:
    """Write a JSON manifest for exported Tableau files.

    Args:
        manifest: Export run metadata.

    Returns:
        Path to the generated manifest JSON file.
    """

    manifest_path = manifest.export_dir / "manifest.json"
    payload = asdict(manifest)
    payload["database_path"] = str(manifest.database_path)
    payload["export_dir"] = str(manifest.export_dir)
    for result in payload["results"]:
        result["path"] = str(result["path"])

    manifest_path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    return manifest_path


def run_exports(
    database_path: Path,
    export_dir: Path,
    file_formats: tuple[str, ...],
) -> ExportManifest:
    """Run all configured Tableau exports.

    Args:
        database_path: DuckDB database containing dbt mart tables.
        export_dir: Directory where export files should be written.
        file_formats: File formats to export.

    Returns:
        Manifest metadata for the export run.
    """

    validate_database(database_path)
    export_dir.mkdir(parents=True, exist_ok=True)

    results: list[ExportResult] = []
    with duckdb.connect(str(database_path), read_only=True) as connection:
        for export_spec in MART_EXPORTS:
            for file_format in file_formats:
                results.append(
                    export_dataset(
                        connection=connection,
                        export_spec=export_spec,
                        export_dir=export_dir,
                        file_format=file_format,
                    )
                )

    manifest = ExportManifest(
        generated_at=datetime.now(UTC).isoformat(),
        database_path=database_path,
        export_dir=export_dir,
        results=tuple(results),
    )
    write_manifest(manifest)
    return manifest


def format_manifest(manifest: ExportManifest) -> str:
    """Format export results for console output.

    Args:
        manifest: Export run metadata.

    Returns:
        Human-readable export summary.
    """

    lines = [
        "RetailPulse Tableau Export",
        "==========================",
        f"Source database: {manifest.database_path}",
        f"Export directory: {manifest.export_dir}",
        "",
        "Files written:",
    ]
    for result in manifest.results:
        lines.append(
            f"- {result.path} "
            f"({result.file_format}, {result.row_count:,} rows)"
        )
    return "\n".join(lines)


def main() -> int:
    """Run the Tableau export command.

    Returns:
        Process exit code. Zero means success; non-zero means a handled error.
    """

    args = parse_args()
    try:
        file_formats = validate_formats(args.formats)
        manifest = run_exports(
            database_path=args.database_path,
            export_dir=args.export_dir,
            file_formats=file_formats,
        )
    except (duckdb.Error, FileNotFoundError, ValueError) as error:
        print(f"Unable to export Tableau files: {error}")
        return 1

    print(format_manifest(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
