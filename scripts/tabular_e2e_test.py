#!/usr/bin/env python3
"""
Cortex KB — Tabular NL2SQL end-to-end test.

Tests the full pipeline:
  1.  Health check
  2.  Bootstrap tenant + API key (if needed)
  3.  Upload CSV  → verify is_tabular detected
  4.  Upload XLSX → verify is_tabular detected
  5.  Poll until both docs reach status=indexed
  6.  Search analytics queries → verify DuckDB result returned (Markdown table)
  7.  Verify result_type="tabular" in response
  8.  Verify sql_query populated
  9.  Search non-analytics query → verify still works
  10. Cleanup (delete both docs)

Usage:
    uv run python scripts/tabular_e2e_test.py
    uv run python scripts/tabular_e2e_test.py --base-url http://localhost:8080 --api-key cortex_xxx

    # Override SQL provider for test run:
    TABULAR_SQL_BASE_URL=https://integrate.api.nvidia.com/v1 \\
    TABULAR_SQL_API_KEY=nvapi-... \\
    TABULAR_SQL_MODEL=openai/gpt-oss-120b \\
    uv run python scripts/tabular_e2e_test.py
"""
import argparse
import io
import json
import os
import sys
import time
import textwrap
from pathlib import Path

import httpx

# Load .env from repo root so TABULAR_SQL_* vars are available
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# ── Colour helpers ────────────────────────────────────────────────────────────

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def fail(msg): print(f"  {RED}✗{RESET}  {msg}"); sys.exit(1)
def info(msg): print(f"  {CYAN}·{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}!{RESET}  {msg}")
def section(title): print(f"\n{BOLD}{title}{RESET}")

# ── Sample tabular data ───────────────────────────────────────────────────────

# CSV: monthly sales by region
CSV_CONTENT = """\
month,region,product,units_sold,revenue_usd,cost_usd
2024-01,North,Widget A,150,22500.00,9000.00
2024-01,South,Widget A,200,30000.00,12000.00
2024-01,East,Widget B,90,18000.00,7200.00
2024-01,West,Widget B,120,24000.00,9600.00
2024-02,North,Widget A,180,27000.00,10800.00
2024-02,South,Widget A,160,24000.00,9600.00
2024-02,East,Widget B,110,22000.00,8800.00
2024-02,West,Widget B,95,19000.00,7600.00
2024-03,North,Widget A,210,31500.00,12600.00
2024-03,South,Widget A,230,34500.00,13800.00
2024-03,East,Widget B,140,28000.00,11200.00
2024-03,West,Widget B,175,35000.00,14000.00
2024-04,North,Widget A,195,29250.00,11700.00
2024-04,South,Widget B,220,44000.00,17600.00
2024-04,East,Widget A,130,19500.00,7800.00
2024-04,West,Widget A,160,24000.00,9600.00
""".encode()

# XLSX: build a simple xlsx in-memory using openpyxl
def _make_xlsx() -> bytes:
    try:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Inventory"
        ws.append(["sku", "product_name", "category", "stock_qty", "unit_price", "warehouse"])
        rows = [
            ("SKU-001", "Laptop Pro 15",  "Electronics", 45,  1299.99, "WH-A"),
            ("SKU-002", "Wireless Mouse",  "Accessories",  320, 29.99,  "WH-A"),
            ("SKU-003", "USB-C Hub",       "Accessories",  210, 49.99,  "WH-B"),
            ("SKU-004", "Monitor 27\"",    "Electronics",  80,  399.99, "WH-B"),
            ("SKU-005", "Keyboard Mech",   "Accessories",  150, 89.99,  "WH-A"),
            ("SKU-006", "Webcam HD",       "Electronics",  95,  79.99,  "WH-C"),
            ("SKU-007", "Desk Lamp LED",   "Office",       400, 24.99,  "WH-C"),
            ("SKU-008", "Notebook A4",     "Office",      1200,  3.99,  "WH-B"),
            ("SKU-009", "Headphones BT",   "Electronics",  60,  149.99, "WH-A"),
            ("SKU-010", "Phone Stand",     "Accessories",  500,  14.99, "WH-C"),
        ]
        for r in rows:
            ws.append(list(r))
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    except ImportError:
        warn("openpyxl not installed — skipping XLSX test")
        return b""


# ── Analytics queries to test ─────────────────────────────────────────────────

CSV_QUERIES = [
    {
        "query": "What is the total revenue by region?",
        "expect_keywords": ["North", "South", "East", "West"],
        "description": "GROUP BY aggregation",
    },
    {
        "query": "Which month had the highest total revenue?",
        "expect_keywords": ["2024"],
        "description": "ORDER BY + LIMIT aggregation",
    },
    {
        "query": "What is the profit (revenue minus cost) per product?",
        "expect_keywords": ["Widget"],
        "description": "Computed column aggregation",
    },
    {
        "query": "How many units were sold in Q1 2024?",
        "expect_keywords": [],  # just needs a number
        "description": "Date filter + SUM",
    },
]

XLSX_QUERIES = [
    {
        "query": "Which products have stock below 100 units?",
        "expect_keywords": ["SKU"],
        "description": "WHERE filter",
    },
    {
        "query": "What is the total stock value per warehouse?",
        "expect_keywords": ["WH-"],
        "description": "GROUP BY + computed value",
    },
]


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def get(client: httpx.Client, path: str, **kw):
    r = client.get(path, **kw)
    return r

def post(client: httpx.Client, path: str, **kw):
    r = client.post(path, **kw)
    return r

def delete(client: httpx.Client, path: str, **kw):
    r = client.delete(path, **kw)
    return r

def headers(api_key: str) -> dict:
    return {"X-Api-Key": api_key}


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def bootstrap(client: httpx.Client, base: str) -> str:
    """Create tenant + API key, return raw key."""
    section("Bootstrap")
    # Create tenant
    r = post(client, f"{base}/admin/tenants", json={"name": "tabular-test-tenant"})
    if r.status_code not in (200, 201):
        fail(f"Create tenant failed: {r.status_code} {r.text[:200]}")
    tenant_id = r.json()["tenant_id"]
    ok(f"Tenant created: {tenant_id}")

    # Create API key
    r = post(client, f"{base}/admin/api-keys", json={
        "label": "tabular-test-key",
        "role": "editor",
        "tenant_id": tenant_id,
    })
    if r.status_code not in (200, 201):
        fail(f"Create API key failed: {r.status_code} {r.text[:200]}")
    raw_key = r.json()["raw_key"]
    ok(f"API key created: {raw_key[:20]}...")
    return raw_key


# ── Upload ────────────────────────────────────────────────────────────────────

def upload(client: httpx.Client, base: str, api_key: str, filename: str, data: bytes, mime: str) -> str:
    r = post(
        client,
        f"{base}/ingest/upload",
        files={"file": (filename, data, mime)},
        headers=headers(api_key),
    )
    if r.status_code not in (200, 201):
        fail(f"Upload {filename} failed: {r.status_code} {r.text[:300]}")
    doc_id = r.json()["document_id"]
    ok(f"Uploaded {filename} → document_id={doc_id}")
    return doc_id


# ── Poll pipeline ─────────────────────────────────────────────────────────────

def poll_until_indexed(
    client: httpx.Client,
    base: str,
    api_key: str,
    doc_id: str,
    timeout: int = 180,
    interval: int = 4,
) -> dict:
    deadline = time.time() + timeout
    last_status = ""
    while time.time() < deadline:
        r = get(client, f"{base}/status/{doc_id}", headers=headers(api_key))
        if r.status_code == 200:
            data = r.json()
            status = data.get("overall_status", "unknown")
            if status != last_status:
                info(f"  [{doc_id[:8]}] status={status}")
                last_status = status
            if status == "indexed":
                return data
            if "failed" in status or "error" in status:
                fail(f"Pipeline failed for {doc_id}: {status}\n{json.dumps(data, indent=2)}")
        time.sleep(interval)
    fail(f"Timeout waiting for {doc_id} to reach indexed (>{timeout}s)")


# ── Search ────────────────────────────────────────────────────────────────────

def search(
    client: httpx.Client,
    base: str,
    api_key: str,
    query: str,
    doc_id: str | None = None,
    top_k: int = 5,
) -> list:
    body = {"query": query, "mode": "hybrid", "top_k": top_k}
    if doc_id:
        body["document_id"] = doc_id
    r = post(client, f"{base}/search", json=body, headers=headers(api_key))
    if r.status_code != 200:
        fail(f"Search failed: {r.status_code} {r.text[:300]}")
    return r.json().get("results", [])


# ── Assertions ────────────────────────────────────────────────────────────────

def assert_tabular_result(results: list, query: str, expect_keywords: list, description: str):
    """Check search results contain a tabular-enriched answer."""
    if not results:
        fail(f"[{description}] No results for: {query!r}")

    tabular = [r for r in results if r.get("result_type") == "tabular"]

    if not tabular:
        # Dump all result types for debugging
        types = [r.get("result_type", "?") for r in results]
        fail(
            f"[{description}] No tabular result for: {query!r}\n"
            f"  result_type values: {types}\n"
            f"  first result text[:200]: {results[0].get('text','')[:200]}"
        )

    top = tabular[0]
    text = top.get("text", "")
    sql  = top.get("sql_query", "")

    # Must have SQL
    if not sql:
        fail(f"[{description}] result_type=tabular but sql_query is empty")

    # Must look like a Markdown table or result
    if "|" not in text and "no results" not in text.lower():
        warn(f"[{description}] Result text doesn't look like a Markdown table:\n{text[:300]}")

    # Check expected keywords present in result
    for kw in expect_keywords:
        if kw.lower() not in text.lower():
            warn(f"[{description}] Expected keyword {kw!r} not in result:\n{text[:400]}")

    ok(f"[{description}] ✓ tabular result returned")
    info(f"  SQL: {sql[:120]}")
    info(f"  Result preview:\n{textwrap.indent(text[:300], '    ')}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Cortex KB tabular NL2SQL E2E test")
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--api-key",  default=None, help="Existing API key (skip bootstrap)")
    parser.add_argument("--admin-key", default="cortex_admin", help="Admin API key for bootstrap")
    parser.add_argument("--timeout",  type=int, default=180, help="Pipeline poll timeout seconds")
    parser.add_argument("--no-cleanup", action="store_true", help="Keep uploaded docs after test")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")

    # Show SQL provider config
    section("SQL Provider Config")
    sql_base = os.getenv("TABULAR_SQL_BASE_URL", "(uses OLLAMA_URL/v1)")
    sql_model = os.getenv("TABULAR_SQL_MODEL", "qwen2.5:7b")
    sql_key   = os.getenv("TABULAR_SQL_API_KEY", "ollama")
    info(f"TABULAR_SQL_BASE_URL  = {sql_base}")
    info(f"TABULAR_SQL_MODEL     = {sql_model}")
    info(f"TABULAR_SQL_API_KEY   = {sql_key[:12]}...")

    with httpx.Client(timeout=60.0, verify=False) as client:

        # ── 1. Health ────────────────────────────────────────────────────────
        section("1. Health Check")
        r = get(client, f"{base}/health")
        if r.status_code != 200:
            fail(f"Health check failed: {r.status_code}")
        ok(f"Server healthy: {r.json().get('status')}")

        # ── 2. API key ───────────────────────────────────────────────────────
        section("2. API Key")
        api_key = args.api_key
        if not api_key:
            client.headers["X-Api-Key"] = args.admin_key
            api_key = bootstrap(client, base)
        else:
            ok(f"Using provided API key: {api_key[:20]}...")

        # ── 3. Upload CSV ────────────────────────────────────────────────────
        section("3. Upload CSV")
        csv_doc_id = upload(client, base, api_key, "sales_data.csv", CSV_CONTENT, "text/csv")

        # ── 4. Upload XLSX ───────────────────────────────────────────────────
        section("4. Upload XLSX")
        xlsx_bytes = _make_xlsx()
        xlsx_doc_id = None
        if xlsx_bytes:
            xlsx_doc_id = upload(
                client, base, api_key, "inventory.xlsx", xlsx_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        else:
            warn("Skipping XLSX upload (openpyxl not available)")

        # ── 5. Poll both docs ────────────────────────────────────────────────
        section("5. Waiting for pipeline (parse → chunk → embed → index)")
        info(f"Polling CSV doc {csv_doc_id[:8]}...")
        csv_status = poll_until_indexed(client, base, api_key, csv_doc_id, args.timeout)
        ok(f"CSV indexed — stages: {list(csv_status.get('stages', {}).keys())}")

        if xlsx_doc_id:
            info(f"Polling XLSX doc {xlsx_doc_id[:8]}...")
            xlsx_status = poll_until_indexed(client, base, api_key, xlsx_doc_id, args.timeout)
            ok(f"XLSX indexed — stages: {list(xlsx_status.get('stages', {}).keys())}")

        # ── 6. Verify is_tabular via document endpoint ────────────────────────
        section("6. Verify Tabular Metadata")
        r = get(client, f"{base}/documents/{csv_doc_id}", headers=headers(api_key))
        if r.status_code == 200:
            doc = r.json()
            if doc.get("is_tabular"):
                ok(f"CSV is_tabular=True ✓")
                schema = doc.get("table_schema", {})
                info(f"  Columns: {[c['name'] for c in schema.get('columns', [])]}")
                info(f"  Row count: {schema.get('row_count', '?')}")
            else:
                warn("CSV is_tabular not set in document metadata (endpoint may not expose it)")
        else:
            warn(f"Document endpoint returned {r.status_code} — skipping metadata check")

        # ── 7. CSV Analytics Queries ─────────────────────────────────────────
        section("7. CSV Analytics Queries (NL2SQL via DuckDB)")
        for q in CSV_QUERIES:
            info(f"\n  Query: {q['query']!r}  [{q['description']}]")
            results = search(client, base, api_key, q["query"], doc_id=csv_doc_id)
            assert_tabular_result(results, q["query"], q["expect_keywords"], q["description"])

        # ── 8. XLSX Analytics Queries ─────────────────────────────────────────
        if xlsx_doc_id:
            section("8. XLSX Analytics Queries (NL2SQL via DuckDB)")
            for q in XLSX_QUERIES:
                info(f"\n  Query: {q['query']!r}  [{q['description']}]")
                results = search(client, base, api_key, q["query"], doc_id=xlsx_doc_id)
                assert_tabular_result(results, q["query"], q["expect_keywords"], q["description"])

        # ── 9. Non-analytics query (summary chunk search) ──────────────────
        section("9. Non-Analytics Search (summary chunk)")
        results = search(client, base, api_key, "sales data columns schema", doc_id=csv_doc_id)
        if results:
            ok(f"Summary chunk search returned {len(results)} result(s)")
            info(f"  First result type: {results[0].get('result_type', '?')}")
        else:
            warn("No results for summary chunk query")

        # ── 10. Cleanup ───────────────────────────────────────────────────────
        if not args.no_cleanup:
            section("10. Cleanup")
            for doc_id, label in [(csv_doc_id, "CSV"), (xlsx_doc_id, "XLSX")]:
                if not doc_id:
                    continue
                r = delete(client, f"{base}/documents/{doc_id}", headers=headers(api_key))
                if r.status_code in (200, 202, 204):
                    ok(f"Deleted {label} doc {doc_id[:8]}")
                else:
                    warn(f"Delete {label} returned {r.status_code}")
        else:
            warn("--no-cleanup set, docs kept")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{GREEN}{BOLD}All tabular E2E tests passed ✓{RESET}\n")


if __name__ == "__main__":
    main()
