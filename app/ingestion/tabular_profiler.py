"""
Tabular document profiler.

Downloads CSV / XLSX from MinIO, profiles schema with DuckDB (runs in a thread
pool so DuckDB's GIL-bound operations don't block the event loop), generates a
plain-text summary chunk for vector + FTS indexing, and stores structured schema
metadata in documents.table_schema.

Supported input types
---------------------
- text/csv  |  .csv
- text/tab-separated-values  |  .tsv
- application/vnd.openxmlformats-officedocument.spreadsheetml.sheet  |  .xlsx
- application/vnd.ms-excel  |  .xls  (first sheet only)
"""
import asyncio
import csv
import io
import os
import tempfile
from typing import Optional

import duckdb
import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# MIME / extension detection
# ---------------------------------------------------------------------------

TABULAR_MIMES = frozenset({
    "text/csv",
    "text/tab-separated-values",
    "application/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
})

TABULAR_EXTENSIONS = frozenset({".csv", ".tsv", ".xlsx", ".xls"})

_XLSX_MIMES = frozenset({
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
})


def is_tabular(filename: str, mime_type: str) -> bool:
    """Return True if this file should be handled by the tabular pipeline."""
    mime = mime_type.lower().split(";")[0].strip()
    ext = os.path.splitext(filename.lower())[1]
    return mime in TABULAR_MIMES or ext in TABULAR_EXTENSIONS


# ---------------------------------------------------------------------------
# XLSX → CSV conversion (pure Python, no pandas)
# ---------------------------------------------------------------------------

def _xlsx_to_csv_bytes(data: bytes, sheet_name: Optional[str] = None) -> tuple[bytes, str]:
    """
    Convert an XLSX/XLS workbook to UTF-8 CSV bytes.
    Returns (csv_bytes, actual_sheet_name).
    """
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb.active
    actual_sheet: str = ws.title  # type: ignore[assignment]

    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    for row in ws.iter_rows(values_only=True):  # type: ignore[union-attr]
        writer.writerow(["" if v is None else str(v) for v in row])
    wb.close()

    return buf.getvalue().encode("utf-8"), actual_sheet


# ---------------------------------------------------------------------------
# DuckDB profiling (blocking — run in executor)
# ---------------------------------------------------------------------------

def _profile_sync(filename: str, data: bytes, mime_type: str) -> dict:
    """
    Profile a tabular file using DuckDB.

    Returns:
        {
            "columns": [
                {"name": str, "type": str, "sample": [str, ...]},
                ...
            ],
            "row_count": int,
            "sheet_name": str | None,
        }
    """
    mime = mime_type.lower().split(";")[0].strip()
    ext  = os.path.splitext(filename.lower())[1]

    sheet_name: Optional[str] = None
    csv_data = data

    # Convert XLSX → CSV in-memory
    if mime in _XLSX_MIMES or ext in (".xlsx", ".xls"):
        csv_data, sheet_name = _xlsx_to_csv_bytes(data)

    # Write CSV to a temp file (DuckDB read_csv_auto needs a path)
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        f.write(csv_data)
        tmp_path = f.name

    try:
        conn = duckdb.connect(":memory:")

        # ── Schema ───────────────────────────────────────────────────────────
        desc_rows = conn.execute(
            f"DESCRIBE SELECT * FROM read_csv_auto('{tmp_path}', header=true, sample_size=2000)"
        ).fetchall()
        # desc_rows columns: column_name, column_type, null, key, default, extra

        col_names = [r[0] for r in desc_rows]

        # ── Sample values (first 5 rows) ─────────────────────────────────────
        sample_rows = conn.execute(
            f"SELECT * FROM read_csv_auto('{tmp_path}', header=true) LIMIT 5"
        ).fetchall()

        # ── Row count ────────────────────────────────────────────────────────
        row_count: int = conn.execute(
            f"SELECT COUNT(*) FROM read_csv_auto('{tmp_path}', header=true)"
        ).fetchone()[0]  # type: ignore[index]

        conn.close()

        columns = []
        for i, row in enumerate(desc_rows):
            samples = [
                str(sr[i])
                for sr in sample_rows
                if i < len(sr) and sr[i] is not None and str(sr[i]).strip()
            ][:5]
            columns.append({
                "name":   row[0],
                "type":   row[1],
                "sample": samples,
            })

        return {
            "columns":    columns,
            "row_count":  row_count,
            "sheet_name": sheet_name,
        }

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Async wrapper
# ---------------------------------------------------------------------------

async def profile_tabular(filename: str, data: bytes, mime_type: str) -> dict:
    """
    Async wrapper around `_profile_sync`.  Runs DuckDB in the default thread
    executor so the event loop stays responsive.
    """
    loop = asyncio.get_event_loop()
    schema = await loop.run_in_executor(None, _profile_sync, filename, data, mime_type)
    log.info(
        "tabular_profiled",
        filename=filename,
        columns=len(schema["columns"]),
        row_count=schema["row_count"],
        sheet=schema.get("sheet_name"),
    )
    return schema


# ---------------------------------------------------------------------------
# Summary chunk builder
# ---------------------------------------------------------------------------

def build_summary_chunk(filename: str, schema: dict) -> str:
    """
    Build a human-readable summary of the tabular file for embedding + FTS.

    This text becomes the single Chunk stored in Postgres / Qdrant so that
    normal hybrid search can surface the document, after which the search
    engine enriches the result with an actual DuckDB NL2SQL answer.
    """
    cols      = schema.get("columns", [])
    row_count = schema.get("row_count", 0)
    sheet     = schema.get("sheet_name")

    col_desc = ", ".join(
        f"{c['name']} ({c['type']})" for c in cols[:30]
    )

    # Show sample values for the first few columns to improve semantic matching
    sample_lines = []
    for c in cols[:5]:
        if c.get("sample"):
            sample_lines.append(
                f"  • {c['name']}: {', '.join(c['sample'][:3])}"
            )
    sample_text = ("\nSample values:\n" + "\n".join(sample_lines)) if sample_lines else ""

    sheet_info = f" Sheet: {sheet}." if sheet else ""
    return (
        f"Tabular data file: {filename}.{sheet_info} "
        f"Contains {row_count:,} rows with {len(cols)} columns.\n"
        f"Columns: {col_desc}.{sample_text}\n"
        f"This file supports analytics queries such as aggregations, filtering, "
        f"grouping, trends, comparisons, totals, averages, and counts."
    )
