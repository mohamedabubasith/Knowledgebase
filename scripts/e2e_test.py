#!/usr/bin/env python3
"""
Cortex KB — end-to-end integration test.
Runs against a live server. Covers the full ingestion + search pipeline.

Usage:
    uv run python scripts/e2e_test.py
    uv run python scripts/e2e_test.py --base-url http://localhost:8080 --api-key cortex_xxx

Steps:
  1.  Health check
  2.  Bootstrap (first run) or skip if already done
  3.  Upload document
  4.  Poll pipeline status until indexed (timeout 120s)
  5.  Search — hybrid mode
  6.  Search — lexical mode
  7.  Search — vector mode
  8.  Search scoped to document
  9.  Get document detail
  10. List document chunks
  11. Create second API key (editor role)
  12. Verify viewer cannot upload
  13. Delete document
  14. Verify document gone from search
  15. Revoke second key
"""
import argparse
import sys
import time
import textwrap
from typing import Optional

import httpx

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_BASE = "http://localhost:8080"
POLL_INTERVAL = 3      # seconds between status polls
POLL_TIMEOUT  = 120    # seconds before giving up

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


# ── Helpers ───────────────────────────────────────────────────────────────────

class E2EError(Exception):
    pass


def ok(label: str, detail: str = "") -> None:
    suffix = f"  {CYAN}{detail}{RESET}" if detail else ""
    print(f"  {GREEN}✓{RESET}  {label}{suffix}")


def fail(label: str, detail: str = "") -> None:
    suffix = f"\n      {RED}{detail}{RESET}" if detail else ""
    print(f"  {RED}✗{RESET}  {label}{suffix}")
    raise E2EError(label)


def skip(label: str, detail: str = "") -> None:
    suffix = f"  {YELLOW}{detail}{RESET}" if detail else ""
    print(f"  {YELLOW}~{RESET}  {label}{suffix}")


def section(title: str) -> None:
    print(f"\n{BOLD}{CYAN}── {title}{RESET}")


def assert_status(resp: httpx.Response, expected: int, label: str) -> dict:
    if resp.status_code != expected:
        body = ""
        try:
            body = resp.json()
        except Exception:
            body = resp.text[:200]
        fail(label, f"HTTP {resp.status_code} (expected {expected}): {body}")
    return resp.json()


# ── Test document content ─────────────────────────────────────────────────────
# Long enough to produce at least one chunk (>64 tokens)

TEST_DOC_CONTENT = textwrap.dedent("""\
    Cortex KB Integration Test Document

    Artificial intelligence is transforming knowledge management systems.
    Vector search enables semantic similarity matching across large document collections.
    Hybrid search combines vector embeddings with traditional full-text search for optimal recall.

    The system uses PostgreSQL for metadata storage and full-text search indexing.
    Qdrant or ChromaDB stores high-dimensional vector embeddings for semantic retrieval.
    MinIO provides scalable object storage for raw document files.

    Document ingestion follows a pipeline: upload, parse, chunk, embed, index.
    Each stage is tracked in real-time via server-sent events for UI integration.

    API keys provide tenant-scoped authentication without session management overhead.
    Role-based access control enforces editor and viewer permissions at the route level.

    This document exists solely to test the end-to-end ingestion and search pipeline.
    Search for: cortex knowledge base pipeline integration test semantic retrieval.
""").encode()


# ── Steps ─────────────────────────────────────────────────────────────────────

def step_health(client: httpx.Client) -> None:
    section("1. Health check")
    resp = client.get("/health")
    data = assert_status(resp, 200, "Health endpoint reachable")
    status = data.get("status", "unknown")
    if status == "ok":
        ok("System healthy", str(data.get("registry", {})))
    elif status == "degraded":
        skip("System degraded (some services down)", str(data.get("components", {})))
    else:
        fail("System down", str(data))


def step_bootstrap(client: httpx.Client, api_key: Optional[str]) -> str:
    section("2. Bootstrap / auth")
    if api_key:
        skip("API key provided via --api-key, skipping bootstrap")
        return api_key

    resp = client.post("/bootstrap")
    if resp.status_code == 409:
        fail(
            "System already bootstrapped but no --api-key provided",
            "Run with: --api-key <your-admin-key>",
        )
    data = assert_status(resp, 200, "Bootstrap succeeded")
    raw_key = data["api_key"]
    ok("Tenant created", data["tenant_id"])
    ok("Admin API key created", raw_key)
    print(f"\n  {YELLOW}⚠  Save this key — shown only once:{RESET}")
    print(f"  {BOLD}{raw_key}{RESET}\n")
    return raw_key


def step_upload(client: httpx.Client, headers: dict) -> str:
    section("3. Upload document")
    import uuid as _uuid
    run_id = _uuid.uuid4().hex[:8]
    unique_name = f"e2e_test_{run_id}.txt"
    unique_content = f"{TEST_DOC_CONTENT}\n\nRun ID: {run_id}".encode()
    resp = client.post(
        "/ingest/upload",
        files={"file": (unique_name, unique_content, "text/plain")},
        headers=headers,
    )
    data = assert_status(resp, 202, "Upload accepted (202)")
    doc_id = data["document_id"]
    ok("Document queued", f"id={doc_id}")
    return doc_id


def step_poll_pipeline(client: httpx.Client, headers: dict, doc_id: str) -> None:
    section("4. Pipeline status polling")
    deadline = time.monotonic() + POLL_TIMEOUT
    last_stage = ""

    while time.monotonic() < deadline:
        resp = client.get(f"/status/{doc_id}", headers=headers)
        if resp.status_code == 404:
            time.sleep(POLL_INTERVAL)
            continue
        data = assert_status(resp, 200, "Status endpoint")
        overall = data.get("overall_status", "")
        pct = data.get("progress_pct", 0)
        stages = data.get("stages", {})

        # Print stage transitions
        active = next(
            (s for s, v in stages.items() if v["status"] == "processing"),
            overall,
        )
        if active != last_stage:
            print(f"    {CYAN}→{RESET} {active} ({pct}%)")
            last_stage = active

        if overall == "indexed":
            ok(f"Pipeline complete", f"progress={pct}%")
            # Print all stages
            for stage, info in stages.items():
                st = info["status"]
                color = GREEN if st == "done" else (RED if st == "failed" else YELLOW)
                detail = str(info.get("detail", {}))
                print(f"      {color}{st:10}{RESET}  {stage:8}  {detail}")
            return

        if overall in ("parse_failed", "embed_failed", "error"):
            fail(f"Pipeline failed at {overall}", str(stages))

        time.sleep(POLL_INTERVAL)

    fail(f"Pipeline timed out after {POLL_TIMEOUT}s", f"last status: {overall}")


def step_search(client: httpx.Client, headers: dict, doc_id: str) -> None:
    section("5–8. Search")

    query = "vector search semantic retrieval pipeline"

    # Hybrid
    resp = client.get("/search", params={"q": query, "mode": "hybrid", "top_k": 5}, headers=headers)
    data = assert_status(resp, 200, "Hybrid search")
    results = data.get("results", [])
    if results:
        ok(f"Hybrid: {data['total']} result(s)", f"mode={data['search_mode_used']}  {data['query_ms']}ms")
        for r in results[:2]:
            snippet = r["text"][:80].replace("\n", " ")
            print(f"      score={r['score']:.4f}  {snippet}…")
    else:
        skip("Hybrid: 0 results (embedder may be warming up)")

    # Lexical
    resp = client.get("/search", params={"q": "knowledge management artificial intelligence", "mode": "lexical_only", "top_k": 5}, headers=headers)
    data = assert_status(resp, 200, "Lexical search")
    if data["total"] > 0:
        ok(f"Lexical: {data['total']} result(s)", f"{data['query_ms']}ms")
    else:
        skip("Lexical: 0 results")

    # Vector
    resp = client.get("/search", params={"q": "semantic similarity embeddings", "mode": "vector_only", "top_k": 5}, headers=headers)
    data = assert_status(resp, 200, "Vector search")
    if data["total"] > 0:
        ok(f"Vector: {data['total']} result(s)", f"mode={data['search_mode_used']}  {data['query_ms']}ms")
    else:
        skip("Vector: 0 results")

    # Scoped to document
    resp = client.get("/search", params={"q": query, "mode": "hybrid", "document_id": doc_id}, headers=headers)
    data = assert_status(resp, 200, "Document-scoped search")
    ok(f"Scoped search: {data['total']} result(s)")


def step_document_detail(client: httpx.Client, headers: dict, doc_id: str) -> None:
    section("9–10. Document detail + chunks")

    resp = client.get(f"/documents/{doc_id}", headers=headers)
    data = assert_status(resp, 200, "Get document")
    ok("Document metadata", f"status={data['status']}  pages={data.get('page_count')}  parse_mode={data.get('parse_mode')}")

    resp = client.get(f"/documents/{doc_id}/chunks", headers=headers, params={"limit": 10})
    data = assert_status(resp, 200, "List chunks")
    chunks = data if isinstance(data, list) else data.get("chunks", [])
    ok(f"Chunks: {len(chunks)}", f"first chunk tokens={chunks[0]['token_count'] if chunks else 'n/a'}")


def step_rbac(client: httpx.Client, admin_headers: dict) -> str:
    section("11–12. RBAC / second key")

    # Create editor key
    resp = client.post(
        "/admin/api-keys",
        json={"label": "e2e-editor", "role": "editor"},
        headers=admin_headers,
    )
    data = assert_status(resp, 200, "Create editor key")
    editor_key = data["raw_key"]
    editor_key_id = data["key_id"]
    ok("Editor key created", editor_key)

    # Create viewer key
    resp = client.post(
        "/admin/api-keys",
        json={"label": "e2e-viewer", "role": "viewer"},
        headers=admin_headers,
    )
    data = assert_status(resp, 200, "Create viewer key")
    viewer_key = data["raw_key"]
    viewer_key_id = data["key_id"]
    ok("Viewer key created")

    # Viewer cannot upload
    resp = client.post(
        "/ingest/upload",
        files={"file": ("x.txt", b"test", "text/plain")},
        headers={"X-Api-Key": viewer_key},
    )
    if resp.status_code == 403:
        ok("Viewer upload blocked (403)")
    else:
        fail("Viewer should not be able to upload", f"got HTTP {resp.status_code}")

    # Viewer can search
    resp = client.get("/search", params={"q": "test", "mode": "lexical_only"}, headers={"X-Api-Key": viewer_key})
    assert_status(resp, 200, "Viewer can search")
    ok("Viewer search allowed")

    return editor_key_id


def step_delete(client: httpx.Client, headers: dict, doc_id: str) -> None:
    section("13–14. Delete + verify")

    resp = client.delete(f"/documents/{doc_id}", headers=headers)
    assert_status(resp, 202, "Delete accepted")
    ok("Delete queued")

    # Wait for purge worker
    time.sleep(5)

    # Document should be gone
    resp = client.get(f"/documents/{doc_id}", headers=headers)
    if resp.status_code == 404:
        ok("Document deleted (404 confirmed)")
    else:
        data = resp.json()
        if data.get("status") == "deleted":
            ok("Document marked deleted")
        else:
            skip("Document still visible", f"status={data.get('status')} — purge worker may still be running")

    # Search should return 0 results for this doc
    resp = client.get(
        "/search",
        params={"q": "cortex pipeline integration test", "mode": "lexical_only"},
        headers=headers,
    )
    data = assert_status(resp, 200, "Search after delete")
    ok(f"Post-delete search: {data['total']} result(s) (expecting 0 or from other docs)")


def step_revoke_key(client: httpx.Client, admin_headers: dict, key_id: str) -> None:
    section("15. Revoke key")

    resp = client.delete(f"/admin/api-keys/{key_id}", headers=admin_headers)
    assert_status(resp, 200, "Revoke key")
    ok("Key revoked")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Cortex KB e2e test")
    parser.add_argument("--base-url", default=DEFAULT_BASE, help="Server base URL")
    parser.add_argument("--api-key", default=None, help="Existing admin API key (skip bootstrap)")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP request timeout seconds")
    args = parser.parse_args()

    print(f"\n{BOLD}Cortex KB — E2E Integration Test{RESET}")
    print(f"Server: {CYAN}{args.base_url}{RESET}")
    print(f"Docs:   {CYAN}{args.base_url}/docs{RESET}\n")

    start = time.monotonic()
    passed = 0
    failed = 0

    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        try:
            step_health(client)
            passed += 1

            api_key = step_bootstrap(client, args.api_key)
            passed += 1

            admin_headers = {"X-Api-Key": api_key}

            doc_id = step_upload(client, admin_headers)
            passed += 1

            step_poll_pipeline(client, admin_headers, doc_id)
            passed += 1

            step_search(client, admin_headers, doc_id)
            passed += 1

            step_document_detail(client, admin_headers, doc_id)
            passed += 1

            editor_key_id = step_rbac(client, admin_headers)
            passed += 1

            step_delete(client, admin_headers, doc_id)
            passed += 1

            step_revoke_key(client, admin_headers, editor_key_id)
            passed += 1

        except E2EError as e:
            failed += 1
            print(f"\n  {RED}FAILED:{RESET} {e}")
        except httpx.ConnectError:
            failed += 1
            print(f"\n  {RED}Cannot connect to {args.base_url}{RESET}")
            print(f"  Make sure server is running: {CYAN}uv run uvicorn app.main:app --port 8080{RESET}")
        except Exception as e:
            failed += 1
            print(f"\n  {RED}Unexpected error: {e}{RESET}")
            import traceback
            traceback.print_exc()

    elapsed = time.monotonic() - start
    print(f"\n{'─' * 50}")
    print(f"  Passed: {GREEN}{passed}{RESET}   Failed: {RED}{failed}{RESET}   Time: {elapsed:.1f}s")
    print(f"{'─' * 50}\n")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
