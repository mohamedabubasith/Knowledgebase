"""
MindsDB HTTP client — file upload, SQL execution, file deletion.

File naming: document UUIDs use hyphens which are invalid SQL identifiers.
We store files as `doc_{uuid_no_dashes}` and expose `mindsdb_name(doc_id)` for callers.
"""
import re
import ssl
import urllib.error
import urllib.request
import json
from typing import Optional

import structlog

from app.core.config import settings

log = structlog.get_logger(__name__)

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def mindsdb_name(document_id: str) -> str:
    """Convert UUID → valid MindsDB file/table identifier."""
    return "doc_" + document_id.replace("-", "_")


def _base() -> str:
    return settings.mindsdb_url.rstrip("/")


def _sql_request(query: str) -> dict:
    data = json.dumps({"query": query}).encode()
    req = urllib.request.Request(
        f"{_base()}/api/sql/query",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, context=_ctx, timeout=120) as r:
        return json.loads(r.read())


def upload_file(name: str, csv_bytes: bytes) -> bool:
    """PUT /api/files/{name} — upload CSV bytes. Returns True on success."""
    boundary = "----mdbupload"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{name}.csv"\r\n'
        f"Content-Type: text/csv\r\n\r\n"
    ).encode() + csv_bytes + (
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="original_file_name"\r\n\r\n'
        f"{name}.csv\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="source_type"\r\n\r\n'
        f"file\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    req = urllib.request.Request(
        f"{_base()}/api/files/{name}",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, context=_ctx, timeout=300) as r:
            r.read()
            return True
    except urllib.error.HTTPError as e:
        log.error("mindsdb_upload_failed", name=name, status=e.code, error=e.read().decode())
        return False
    except Exception as e:
        log.error("mindsdb_upload_error", name=name, error=str(e))
        return False


def delete_file(name: str) -> bool:
    """DELETE /api/files/{name}. Returns True on success or already gone."""
    req = urllib.request.Request(
        f"{_base()}/api/files/{name}",
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(req, context=_ctx, timeout=30) as r:
            r.read()
            return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return True
        log.error("mindsdb_delete_failed", name=name, status=e.code)
        return False
    except Exception as e:
        log.error("mindsdb_delete_error", name=name, error=str(e))
        return False


def sql_query(query: str) -> tuple[list[str], list[list], int]:
    """
    Execute SQL against MindsDB. Returns (headers, rows, total_rows).
    Raises RuntimeError on MindsDB error response.
    """
    resp = _sql_request(query)
    if resp.get("type") == "error":
        raise RuntimeError(resp.get("error_message", "MindsDB SQL error"))
    headers: list[str] = resp.get("column_names", [])
    data: list[list] = resp.get("data", [])
    return headers, data, len(data)


def get_row_count(mindsdb_file_name: str) -> int:
    """Run COUNT(*) against a MindsDB file table."""
    _, rows, _ = sql_query(f"SELECT COUNT(*) AS cnt FROM files.`{mindsdb_file_name}`")
    if rows:
        return int(rows[0][0])
    return 0


def get_schema_and_samples(mindsdb_file_name: str) -> tuple[list[dict], int]:
    """
    Returns (columns, row_count) by querying MindsDB.

    columns: [{"name": str, "type": str, "sample": [str, ...]}, ...]
    """
    headers, sample_rows, _ = sql_query(
        f"SELECT * FROM files.`{mindsdb_file_name}` LIMIT 5"
    )
    _, count_rows, _ = sql_query(
        f"SELECT COUNT(*) AS cnt FROM files.`{mindsdb_file_name}`"
    )
    row_count = int(count_rows[0][0]) if count_rows else 0

    columns = []
    for i, h in enumerate(headers):
        samples = [
            str(row[i]) for row in sample_rows
            if i < len(row) and row[i] is not None and str(row[i]).strip()
        ][:5]
        # Simple type inference from samples
        col_type = _infer_type(samples)
        columns.append({"name": h, "type": col_type, "sample": samples})

    return columns, row_count


def _infer_type(samples: list[str]) -> str:
    non_empty = [s for s in samples if s.strip()]
    if not non_empty:
        return "VARCHAR"
    int_pat = re.compile(r"^-?\d+$")
    float_pat = re.compile(r"^-?\d*\.?\d+([eE][+-]?\d+)?$")
    if all(int_pat.match(s.strip()) for s in non_empty):
        return "BIGINT"
    if all(float_pat.match(s.strip()) for s in non_empty):
        return "DOUBLE"
    return "VARCHAR"
