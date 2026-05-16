"""
Tabular NL2SQL engine.

Flow
----
1. Receive natural-language query + document metadata (minio_path, table_schema)
2. Call Ollama to generate a DuckDB-dialect SQL SELECT
3. Validate SQL (read-only whitelist)
4. Download the raw file from MinIO (runs in thread executor)
5. Execute SQL via DuckDB in-process
6. Format results as a Markdown table
7. Return (sql_text, formatted_markdown)

All I/O-bound steps are async; CPU-bound DuckDB execution runs in the default
thread executor so the event loop stays free.
"""
import asyncio
import os
import re
import tempfile
from typing import Optional

import duckdb
import httpx
import structlog

from app.core.config import settings
from app.storage.minio_client import download_file

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# SQL Safety
# ---------------------------------------------------------------------------

_WRITE_OPS = re.compile(
    r"\b(DROP|DELETE|INSERT|UPDATE|CREATE|ALTER|TRUNCATE|REPLACE|GRANT|REVOKE"
    r"|ATTACH|DETACH|COPY|EXPORT|IMPORT|LOAD|INSTALL|PRAGMA)\b",
    re.IGNORECASE,
)


def _validate_sql(sql: str) -> None:
    """Raise ValueError if SQL contains any non-SELECT / write operation."""
    stripped = sql.strip()
    if not stripped.upper().startswith("SELECT") and not stripped.upper().startswith("WITH"):
        raise ValueError(
            f"Generated SQL must start with SELECT or WITH, got: {stripped[:80]!r}"
        )
    if _WRITE_OPS.search(stripped):
        raise ValueError(f"Generated SQL contains a disallowed operation: {stripped[:200]!r}")


# ---------------------------------------------------------------------------
# SQL generation via Ollama
# ---------------------------------------------------------------------------

def _sql_base_url() -> str:
    """
    Resolve the OpenAI-compatible base URL for SQL generation.

    Priority:
      1. TABULAR_SQL_BASE_URL if explicitly set
      2. OLLAMA_URL + /v1  (Ollama exposes OpenAI-compat at /v1)
    """
    if settings.tabular_sql_base_url.strip():
        return settings.tabular_sql_base_url.rstrip("/")
    return settings.ollama_url.rstrip("/") + "/v1"


async def _generate_sql(query: str, schema: dict, filename: str) -> str:
    """
    Call an OpenAI-compatible /chat/completions endpoint to translate `query`
    into a DuckDB SQL SELECT against the `data` table.

    Works with: OpenAI, Groq, together.ai, vLLM, LiteLLM, Ollama (/v1), etc.
    Returns the cleaned SQL string (no markdown fences, no trailing semicolons).
    """
    cols      = schema.get("columns", [])
    row_count = schema.get("row_count", 0)

    col_lines = []
    for c in cols:
        samples     = c.get("sample", [])
        sample_note = (
            f" — e.g. {', '.join(repr(s) for s in samples[:2])}"
            if samples else ""
        )
        col_lines.append(f"  {c['name']}  {c['type']}{sample_note}")
    cols_block = "\n".join(col_lines)

    system_msg = (
        "You are a DuckDB SQL expert. "
        "You write precise, read-only SQL SELECT queries. "
        "Return ONLY the SQL statement — no explanation, no markdown fences, "
        "no trailing semicolons."
    )
    user_msg = (
        f"Table name : `data`\n"
        f"Source file: {filename}\n"
        f"Total rows : {row_count:,}\n"
        f"Columns:\n{cols_block}\n\n"
        f"Rules:\n"
        f"- Only SELECT or WITH … SELECT queries (no writes, no DDL)\n"
        f"- Table name is always `data`\n"
        f"- LIMIT to {settings.tabular_max_result_rows} rows unless the question explicitly "
        f"requests a different limit\n"
        f"- Use DuckDB SQL syntax (strftime, epoch, COLUMNS, EXCLUDE, etc.)\n"
        f"- Cast or coerce types as needed (TRY_CAST is available)\n\n"
        f"Question: {query}\n\n"
        f"SQL:"
    )

    base_url = _sql_base_url()
    api_key  = settings.tabular_sql_api_key or "ollama"
    model    = settings.tabular_sql_model

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model":    model,
                    "messages": [
                        {"role": "system", "content": system_msg},
                        {"role": "user",   "content": user_msg},
                    ],
                    "temperature": 0.05,
                    "max_tokens":  512,
                    "stream":      False,
                },
            )
            resp.raise_for_status()
            data    = resp.json()
            raw_sql = data["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"SQL provider returned HTTP {exc.response.status_code} — check "
            f"TABULAR_SQL_BASE_URL / TABULAR_SQL_API_KEY / TABULAR_SQL_MODEL"
        ) from exc
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Unexpected response structure from SQL provider: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"SQL generation call failed: {exc}") from exc

    # Strip markdown fences if model disobeys
    raw_sql = re.sub(r"```sql\s*", "", raw_sql, flags=re.IGNORECASE)
    raw_sql = re.sub(r"```\s*",    "", raw_sql)
    raw_sql = raw_sql.strip().rstrip(";").strip()

    if not raw_sql:
        raise ValueError("SQL provider returned an empty response")

    return raw_sql


# ---------------------------------------------------------------------------
# DuckDB execution (blocking — run in executor)
# ---------------------------------------------------------------------------

def _run_duckdb(csv_path: str, sql: str, max_rows: int) -> tuple[list[str], list[list], int]:
    """
    Execute `sql` against a CSV file via DuckDB.

    Returns (headers, rows, total_matching_rows).
    `rows` is capped at `max_rows`; `total_matching_rows` is the full count so
    the caller can display "showing N of M rows".
    """
    conn = duckdb.connect(":memory:")
    try:
        conn.execute(
            f"CREATE TABLE data AS SELECT * FROM read_csv_auto('{csv_path}', header=true)"
        )

        # Execute the user query (already validated)
        cursor    = conn.execute(sql)
        all_rows  = cursor.fetchall()
        headers   = [d[0] for d in cursor.description]
        total     = len(all_rows)
        rows      = [list(r) for r in all_rows[:max_rows]]
        return headers, rows, total
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------

def _fmt_cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        # Avoid scientific notation for reasonable magnitudes
        if abs(v) < 1e12:
            return f"{v:,.4f}".rstrip("0").rstrip(".")
        return f"{v:.4e}"
    return str(v).replace("|", "\\|")


def _format_markdown(headers: list[str], rows: list[list], total: int) -> str:
    if not rows:
        return "_Query returned no results._"

    lines = [
        "| " + " | ".join(str(h) for h in headers) + " |",
        "| " + " | ".join("---" for _ in headers)  + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_fmt_cell(v) for v in row) + " |")

    md = "\n".join(lines)
    if total > len(rows):
        md += f"\n\n_Showing {len(rows):,} of {total:,} matching rows._"
    return md


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def query_tabular(
    query: str,
    document_id: str,
    minio_path: str,
    table_schema: dict,
    filename: str,
) -> tuple[str, str]:
    """
    Run an NL2SQL query against a tabular document stored in MinIO.

    Parameters
    ----------
    query        : Natural-language question from the user
    document_id  : UUID of the Document row (for logging)
    minio_path   : MinIO object path
    table_schema : Schema dict as stored in documents.table_schema
    filename     : Original filename (for prompt context)

    Returns
    -------
    (sql_text, markdown_result)
    """
    # ── 1. Generate SQL ────────────────────────────────────────────────────
    try:
        sql = await _generate_sql(query, table_schema, filename)
    except Exception as exc:
        log.error("tabular_sql_gen_failed", document_id=document_id, error=str(exc))
        return "", f"_Could not generate SQL for this query: {exc}_"

    log.info("tabular_sql_generated", document_id=document_id, sql=sql[:300])

    # ── 2. Validate ────────────────────────────────────────────────────────
    try:
        _validate_sql(sql)
    except ValueError as exc:
        log.warning("tabular_sql_invalid", document_id=document_id, error=str(exc))
        return sql, f"_Generated SQL was rejected (safety check): {exc}_"

    # ── 3. Download file ───────────────────────────────────────────────────
    try:
        data = await download_file(minio_path)
    except Exception as exc:
        log.error("tabular_download_failed", minio_path=minio_path, error=str(exc))
        return sql, f"_Could not download the source file from storage: {exc}_"

    # ── 4. Convert XLSX → CSV if needed ───────────────────────────────────
    ext = os.path.splitext(filename.lower())[1]
    if ext in (".xlsx", ".xls"):
        try:
            from app.ingestion.tabular_profiler import _xlsx_to_csv_bytes
            data, _ = _xlsx_to_csv_bytes(data)
        except Exception as exc:
            log.error("tabular_xlsx_convert_failed", document_id=document_id, error=str(exc))
            return sql, f"_Failed to convert XLSX to CSV: {exc}_"

    # ── 5. Execute DuckDB in thread pool ───────────────────────────────────
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        f.write(data)
        tmp_path = f.name

    try:
        loop = asyncio.get_event_loop()
        headers, rows, total = await loop.run_in_executor(
            None, _run_duckdb, tmp_path, sql, settings.tabular_max_result_rows
        )
    except Exception as exc:
        log.error("tabular_duckdb_exec_failed", document_id=document_id, sql=sql, error=str(exc))
        return sql, (
            f"_SQL execution failed: {exc}_\n\n"
            f"**Generated SQL:**\n```sql\n{sql}\n```"
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # ── 6. Format result ───────────────────────────────────────────────────
    md = _format_markdown(headers, rows, total)
    log.info(
        "tabular_query_ok",
        document_id=document_id,
        rows_returned=len(rows),
        total_matching=total,
    )
    return sql, md
