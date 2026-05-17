"""
Tabular NL2SQL engine — MindsDB backend.

Flow
----
1. Receive natural-language query + document metadata (document_id, table_schema)
2. Call LLM to generate standard SQL SELECT against MindsDB files table
3. Validate SQL (read-only whitelist)
4. Execute SQL via MindsDB HTTP API
5. Format results as a Markdown table
6. Return (sql_text, formatted_markdown)
"""
import asyncio
import re
from typing import Optional

import httpx
import structlog

from app.core.config import settings
from app.storage import mindsdb_client as mdb

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# SQL Safety
# ---------------------------------------------------------------------------

_WRITE_OPS = re.compile(
    r"\b(DROP|DELETE|INSERT|UPDATE|CREATE|ALTER|TRUNCATE|GRANT|REVOKE"
    r"|ATTACH|DETACH|COPY|EXPORT|IMPORT|LOAD|INSTALL|PRAGMA)\b",
    re.IGNORECASE,
)

_STRIP_LITERALS = re.compile(r"'[^']*'|\"[^\"]*\"")


def _validate_sql(sql: str) -> None:
    stripped = sql.strip()
    if not stripped.upper().startswith("SELECT") and not stripped.upper().startswith("WITH"):
        raise ValueError(
            f"Generated SQL must start with SELECT or WITH, got: {stripped[:80]!r}"
        )
    sanitised = _STRIP_LITERALS.sub("''", stripped)
    if _WRITE_OPS.search(sanitised):
        raise ValueError(f"Generated SQL contains a disallowed operation: {stripped[:200]!r}")


# ---------------------------------------------------------------------------
# SQL generation via LLM
# ---------------------------------------------------------------------------

def _sql_base_url() -> str:
    if settings.tabular_sql_base_url.strip():
        return settings.tabular_sql_base_url.rstrip("/")
    return settings.ollama_url.rstrip("/") + "/v1"


async def _call_llm(messages: list[dict]) -> str:
    base_url = _sql_base_url()
    api_key  = settings.tabular_sql_api_key or "ollama"
    model    = settings.tabular_sql_model

    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model":       model,
                "messages":    messages,
                "temperature": 0.05,
                "max_tokens":  2048,
                "stream":      False,
            },
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"].get("content") or ""
        raw: str = content.strip()

    raw = re.sub(r"```sql\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"```\s*",    "", raw)
    raw = raw.strip().rstrip(";").strip()
    return raw


async def _generate_sql(query: str, schema: dict, filename: str, table_ref: str) -> str:
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
        "You are a SQL expert. "
        "You write precise, read-only SQL SELECT queries compatible with MySQL syntax. "
        "Return ONLY the SQL statement — no explanation, no markdown fences, "
        "no trailing semicolons."
    )
    user_msg = (
        f"Table reference : `{table_ref}`\n"
        f"Source file     : {filename}\n"
        f"Total rows      : {row_count:,}\n"
        f"Columns:\n{cols_block}\n\n"
        f"Rules:\n"
        f"- Only SELECT or WITH … SELECT queries (no writes, no DDL)\n"
        f"- Table name is always `{table_ref}`\n"
        f"- Use standard SQL / MySQL syntax (no DuckDB-specific functions)\n"
        f"- Use CAST for type conversion\n"
        f"- Add LIMIT {settings.tabular_max_result_rows} only when the question asks for specific rows; "
        f"omit LIMIT for aggregations (SUM, COUNT, AVG, GROUP BY)\n\n"
        f"Question: {query}\n\n"
        f"SQL:"
    )

    try:
        raw_sql = await _call_llm([
            {"role": "system", "content": system_msg},
            {"role": "user",   "content": user_msg},
        ])
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"SQL provider returned HTTP {exc.response.status_code} — check "
            f"TABULAR_SQL_BASE_URL / TABULAR_SQL_API_KEY / TABULAR_SQL_MODEL"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"SQL generation call failed: {exc}") from exc

    if not raw_sql:
        log.warning("tabular_sql_empty_response_retrying", query=query[:100])
        simple_user_msg = (
            f"Table: `{table_ref}`  Columns: {', '.join(c['name'] for c in cols)}\n"
            f"Write a SQL SELECT to answer: {query}\n"
            f"SQL only, no explanation."
        )
        try:
            raw_sql = await _call_llm([
                {"role": "system", "content": system_msg},
                {"role": "user",   "content": simple_user_msg},
            ])
        except Exception as exc:
            raise RuntimeError(f"SQL generation retry failed: {exc}") from exc

    if not raw_sql:
        raise ValueError("SQL provider returned an empty response")

    return raw_sql


async def _fix_sql(
    original_sql: str,
    error_msg: str,
    schema: dict,
    filename: str,
    table_ref: str,
) -> str:
    cols_block = "\n".join(
        f"  {c['name']}  {c['type']}" for c in schema.get("columns", [])
    )
    fix_msg = (
        f"The following SQL query failed with an error.\n\n"
        f"Table: `{table_ref}`  |  File: {filename}\n"
        f"Columns:\n{cols_block}\n\n"
        f"Failing SQL:\n{original_sql}\n\n"
        f"Error:\n{error_msg}\n\n"
        f"Write a corrected SQL SELECT that fixes the error. "
        f"Use MySQL-compatible syntax. "
        f"Return ONLY the SQL — no explanation, no fences, no semicolons."
    )
    raw = await _call_llm([
        {"role": "system", "content":
            "You are a SQL expert. Fix broken SQL queries. "
            "Return ONLY the corrected SQL statement."},
        {"role": "user", "content": fix_msg},
    ])
    if not raw:
        raise ValueError("LLM returned empty fix")
    return raw


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------

def _fmt_cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
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
    Run an NL2SQL query against a tabular document via MindsDB.

    Returns (sql_text, markdown_result).
    """
    mdb_name  = mdb.mindsdb_name(document_id)
    table_ref = f"files.`{mdb_name}`"

    # ── 1. Generate SQL ────────────────────────────────────────────────────
    try:
        sql = await _generate_sql(query, table_schema, filename, table_ref)
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

    # ── 3. Execute via MindsDB with retry-on-error ─────────────────────────
    MAX_RETRIES = 2
    last_exc: Optional[Exception] = None
    headers: list[str] = []
    rows: list[list] = []
    total: int = 0

    loop = asyncio.get_event_loop()
    for attempt in range(MAX_RETRIES + 1):
        try:
            headers, rows, total = await loop.run_in_executor(
                None, mdb.sql_query, sql
            )
            if attempt > 0:
                log.info("tabular_sql_fixed", document_id=document_id, attempt=attempt, sql=sql[:200])
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                log.warning(
                    "tabular_mindsdb_error_retrying",
                    document_id=document_id,
                    attempt=attempt + 1,
                    error=str(exc),
                    sql=sql[:200],
                )
                try:
                    fixed = await _fix_sql(sql, str(exc), table_schema, filename, table_ref)
                    _validate_sql(fixed)
                    sql = fixed
                except Exception as fix_exc:
                    log.warning("tabular_fix_failed", error=str(fix_exc))
                    break
            else:
                log.error("tabular_mindsdb_exec_failed", document_id=document_id, sql=sql, error=str(exc))

    if last_exc is not None:
        return sql, (
            f"_SQL execution failed after {MAX_RETRIES} retries: {last_exc}_\n\n"
            f"**Last SQL attempted:**\n```sql\n{sql}\n```"
        )

    # ── 4. Cap result rows ─────────────────────────────────────────────────
    cap = settings.tabular_max_result_rows
    if len(rows) > cap:
        total = len(rows)
        rows  = rows[:cap]

    # ── 5. Format result ───────────────────────────────────────────────────
    md = _format_markdown(headers, rows, total)
    log.info("tabular_query_ok", document_id=document_id, rows_returned=len(rows), total_matching=total)
    return sql, md
