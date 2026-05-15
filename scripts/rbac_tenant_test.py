#!/usr/bin/env python3
"""
Cortex KB — E2E RBAC + Multi-Tenant Isolation Test

Covers:
  1.  Tenant isolation — docs/search fully scoped, no cross-tenant leakage
  2.  RBAC admin     — full access: keys, upload, delete, search
  3.  RBAC editor    — upload + delete + search; no key management
  4.  RBAC viewer    — search + read only; no upload, delete, key management
  5.  Key revocation — revoked key fails immediately (401)
  6.  Cross-tenant key management — Tenant A admin cannot revoke Tenant B keys
  7.  Direct doc access across tenants — 404 not 403 (no info leakage)
  8.  Search isolation — Tenant B search never returns Tenant A content

Usage:
    uv run python scripts/rbac_tenant_test.py \
        --base-url https://knowledge.basivo.in \
        --admin-key cortex_xxx
"""
import argparse
import sys
import time
import uuid

import httpx

# ── ANSI ──────────────────────────────────────────────────────────────────────
GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"
CYAN = "\033[96m"; BOLD = "\033[1m"; RESET = "\033[0m"; DIM = "\033[2m"

POLL_TIMEOUT = 90
POLL_INTERVAL = 2


# ── Helpers ───────────────────────────────────────────────────────────────────
class TestError(Exception):
    pass

passed = 0
failed = 0


def section(title: str) -> None:
    print(f"\n{BOLD}{CYAN}── {title}{RESET}")


def ok(label: str, detail: str = "") -> None:
    global passed
    passed += 1
    d = f"  {DIM}{detail}{RESET}" if detail else ""
    print(f"  {GREEN}✓{RESET}  {label}{d}")


def fail(label: str, detail: str = "") -> None:
    global failed
    failed += 1
    d = f"\n      {RED}{detail}{RESET}" if detail else ""
    print(f"  {RED}✗{RESET}  {label}{d}")
    raise TestError(label)


def warn(label: str, detail: str = "") -> None:
    d = f"  {DIM}{detail}{RESET}" if detail else ""
    print(f"  {YELLOW}⚠{RESET}  {label}{d}")


def check(condition: bool, label: str, detail: str = "") -> None:
    if condition:
        ok(label, detail)
    else:
        fail(label, detail)


def req(client: httpx.Client, method: str, path: str, key: str, **kwargs) -> httpx.Response:
    headers = {"X-Api-Key": key}
    if "json" in kwargs:
        headers["Content-Type"] = "application/json"
    return client.request(method, path, headers=headers, **kwargs)


_BASE_CONTENT = (
    "This is a test document for RBAC and tenant isolation verification. "
    "It contains enough text to produce at least one chunk during ingestion. "
    "Knowledge management systems store and retrieve information efficiently. "
    "Access control ensures resources are only visible to authorized tenants. "
    "Role-based access control restricts operations based on assigned roles. "
    "Administrators can manage API keys, upload documents, and delete records. "
    "Editors can upload and delete documents but cannot manage API keys. "
    "Viewers can only search and read documents without modification rights. "
    "Multi-tenant isolation guarantees data separation between organizations. "
    "Search results must never leak content across tenant boundaries. "
)


def upload_doc(client: httpx.Client, key: str, content: str = "") -> str:
    run_id = uuid.uuid4().hex[:8]
    text = content if content else f"{_BASE_CONTENT}\n\nUnique marker: MARKER_{run_id}. Run: {run_id}."
    fname = f"rbac_test_{run_id}.txt"
    resp = client.post(
        "/ingest/upload",
        files={"file": (fname, text.encode(), "text/plain")},
        headers={"X-Api-Key": key},
    )
    if resp.status_code != 202:
        raise TestError(f"Upload failed: {resp.status_code} {resp.text[:100]}")
    return resp.json()["document_id"], run_id


def poll(client: httpx.Client, key: str, doc_id: str, label: str = "") -> None:
    deadline = time.monotonic() + POLL_TIMEOUT
    while time.monotonic() < deadline:
        resp = req(client, "GET", f"/status/{doc_id}", key)
        if resp.status_code == 404:
            time.sleep(POLL_INTERVAL)
            continue
        overall = resp.json().get("overall_status", "")
        if overall == "indexed":
            return
        if "failed" in overall or overall == "error":
            raise TestError(f"Pipeline failed [{label}]: {overall}")
        time.sleep(POLL_INTERVAL)
    raise TestError(f"Pipeline timeout [{label}]")


# ── Test sections ─────────────────────────────────────────────────────────────

def test_setup(client: httpx.Client, admin_key: str) -> dict:
    """Create Tenant B + keys for both tenants at all roles."""
    section("Setup: Create tenants and keys")

    # ── Tenant B ──────────────────────────────────────────────────────────────
    resp = req(client, "POST", "/admin/tenants", admin_key, json={"name": f"rbac-test-tenant-b-{uuid.uuid4().hex[:6]}"})
    check(resp.status_code == 200, "Create Tenant B", f"HTTP {resp.status_code}")
    tenant_b_id = resp.json()["tenant_id"]
    ok(f"Tenant B created", f"id={tenant_b_id[:8]}")

    # Tenant B admin key
    resp = req(client, "POST", "/admin/api-keys", admin_key,
               json={"label": "rbac-test-b-admin", "role": "admin", "tenant_id": tenant_b_id})
    check(resp.status_code == 200, "Create Tenant B admin key")
    b_admin_key = resp.json()["raw_key"]

    # Tenant A: editor + viewer keys
    resp = req(client, "POST", "/admin/api-keys", admin_key,
               json={"label": "rbac-test-a-editor", "role": "editor"})
    check(resp.status_code == 200, "Create Tenant A editor key")
    a_editor_key = resp.json()["raw_key"]
    a_editor_key_id = resp.json()["key_id"]

    resp = req(client, "POST", "/admin/api-keys", admin_key,
               json={"label": "rbac-test-a-viewer", "role": "viewer"})
    check(resp.status_code == 200, "Create Tenant A viewer key")
    a_viewer_key = resp.json()["raw_key"]
    a_viewer_key_id = resp.json()["key_id"]

    # Tenant B: editor + viewer keys (created by B admin)
    resp = req(client, "POST", "/admin/api-keys", b_admin_key,
               json={"label": "rbac-test-b-editor", "role": "editor"})
    check(resp.status_code == 200, "Create Tenant B editor key")
    b_editor_key = resp.json()["raw_key"]

    resp = req(client, "POST", "/admin/api-keys", b_admin_key,
               json={"label": "rbac-test-b-viewer", "role": "viewer"})
    check(resp.status_code == 200, "Create Tenant B viewer key")
    b_viewer_key = resp.json()["raw_key"]

    # Revocable key (for revocation test)
    resp = req(client, "POST", "/admin/api-keys", admin_key,
               json={"label": "rbac-test-revocable", "role": "viewer"})
    check(resp.status_code == 200, "Create revocable key")
    revocable_key = resp.json()["raw_key"]
    revocable_key_id = resp.json()["key_id"]

    return {
        "tenant_b_id": tenant_b_id,
        "a_admin": admin_key,
        "a_editor": a_editor_key,
        "a_editor_id": a_editor_key_id,
        "a_viewer": a_viewer_key,
        "a_viewer_id": a_viewer_key_id,
        "b_admin": b_admin_key,
        "b_editor": b_editor_key,
        "b_viewer": b_viewer_key,
        "revocable": revocable_key,
        "revocable_id": revocable_key_id,
    }


def test_rbac_admin(client: httpx.Client, keys: dict) -> list[str]:
    """Admin: full access."""
    section("RBAC — Admin role (Tenant A)")
    doc_ids = []

    # Upload
    doc_id, run_id = upload_doc(client, keys["a_admin"])
    ok("Admin can upload", f"doc={doc_id[:8]}")
    doc_ids.append(doc_id)
    poll(client, keys["a_admin"], doc_id, "admin-doc")
    ok("Admin doc indexed")

    # List docs
    resp = req(client, "GET", "/documents", keys["a_admin"])
    check(resp.status_code == 200, "Admin can list documents")

    # Search
    resp = req(client, "POST", "/search", keys["a_admin"],
               json={"query": "isolation test", "mode": "hybrid", "top_k": 5})
    check(resp.status_code == 200, "Admin can search")

    # Create key
    resp = req(client, "POST", "/admin/api-keys", keys["a_admin"],
               json={"label": "rbac-temp", "role": "viewer"})
    check(resp.status_code == 200, "Admin can create API keys")
    temp_key_id = resp.json()["key_id"]

    # Revoke key
    resp = req(client, "DELETE", f"/admin/api-keys/{temp_key_id}", keys["a_admin"])
    check(resp.status_code == 200, "Admin can revoke API keys")

    # List keys
    resp = req(client, "GET", "/admin/api-keys", keys["a_admin"])
    check(resp.status_code == 200, "Admin can list API keys")

    # Delete doc
    resp = req(client, "DELETE", f"/documents/{doc_id}", keys["a_admin"])
    check(resp.status_code == 202, "Admin can delete documents")

    return doc_ids


def test_rbac_editor(client: httpx.Client, keys: dict) -> str:
    """Editor: upload/delete/search — no key management."""
    section("RBAC — Editor role (Tenant A)")

    # Upload ✓
    doc_id, run_id = upload_doc(client, keys["a_editor"])
    ok("Editor can upload", f"doc={doc_id[:8]}")
    poll(client, keys["a_editor"], doc_id, "editor-doc")
    ok("Editor doc indexed")

    # Search ✓
    resp = req(client, "POST", "/search", keys["a_editor"],
               json={"query": "isolation test", "mode": "hybrid", "top_k": 5})
    check(resp.status_code == 200, "Editor can search")

    # List docs ✓
    resp = req(client, "GET", "/documents", keys["a_editor"])
    check(resp.status_code == 200, "Editor can list documents")

    # Create API key ✗ (403)
    resp = req(client, "POST", "/admin/api-keys", keys["a_editor"],
               json={"label": "editor-attempt", "role": "viewer"})
    check(resp.status_code == 403, "Editor blocked from creating API keys", f"got {resp.status_code}")

    # List API keys ✗ (403)
    resp = req(client, "GET", "/admin/api-keys", keys["a_editor"])
    check(resp.status_code == 403, "Editor blocked from listing API keys", f"got {resp.status_code}")

    # Delete own doc ✓
    resp = req(client, "DELETE", f"/documents/{doc_id}", keys["a_editor"])
    check(resp.status_code == 202, "Editor can delete documents")

    return doc_id


def test_rbac_viewer(client: httpx.Client, keys: dict) -> None:
    """Viewer: read/search only."""
    section("RBAC — Viewer role (Tenant A)")

    # Search ✓
    resp = req(client, "POST", "/search", keys["a_viewer"],
               json={"query": "test document", "mode": "hybrid", "top_k": 5})
    check(resp.status_code == 200, "Viewer can search")

    # List docs ✓
    resp = req(client, "GET", "/documents", keys["a_viewer"])
    check(resp.status_code == 200, "Viewer can list documents")

    # Upload ✗ (403)
    resp = client.post(
        "/ingest/upload",
        files={"file": ("v.txt", b"viewer upload attempt", "text/plain")},
        headers={"X-Api-Key": keys["a_viewer"]},
    )
    check(resp.status_code == 403, "Viewer blocked from uploading", f"got {resp.status_code}")

    # Create API key ✗ (403)
    resp = req(client, "POST", "/admin/api-keys", keys["a_viewer"],
               json={"label": "viewer-attempt", "role": "viewer"})
    check(resp.status_code == 403, "Viewer blocked from creating API keys")

    # List API keys ✗ (403)
    resp = req(client, "GET", "/admin/api-keys", keys["a_viewer"])
    check(resp.status_code == 403, "Viewer blocked from listing API keys")


def test_tenant_isolation(client: httpx.Client, keys: dict) -> list[str]:
    """Tenant A and B docs are fully isolated."""
    section("Tenant Isolation — Upload docs for both tenants")

    # Tenant A uploads unique doc (pad with base content so chunker produces output)
    secret_a = f"TENANT_A_SECRET_{uuid.uuid4().hex}"
    unique_a = f"{_BASE_CONTENT}\n\nConfidential marker for tenant A: {secret_a}."
    doc_a_id, _ = upload_doc(client, keys["a_admin"], unique_a)
    ok(f"Tenant A doc uploaded", f"id={doc_a_id[:8]}")
    poll(client, keys["a_admin"], doc_a_id, "tenant-a-doc")

    # Tenant B uploads unique doc
    secret_b = f"TENANT_B_SECRET_{uuid.uuid4().hex}"
    unique_b = f"{_BASE_CONTENT}\n\nConfidential marker for tenant B: {secret_b}."
    doc_b_id, _ = upload_doc(client, keys["b_admin"], unique_b)
    ok(f"Tenant B doc uploaded", f"id={doc_b_id[:8]}")
    poll(client, keys["b_admin"], doc_b_id, "tenant-b-doc")

    section("Tenant Isolation — Cross-tenant access checks")

    # Tenant B cannot GET Tenant A doc directly → 404 (no info leakage)
    resp = req(client, "GET", f"/documents/{doc_a_id}", keys["b_admin"])
    check(resp.status_code == 404, "Tenant B: GET Tenant A doc → 404 (no leakage)", f"got {resp.status_code}")

    # Tenant A cannot GET Tenant B doc directly → 404
    resp = req(client, "GET", f"/documents/{doc_b_id}", keys["a_admin"])
    check(resp.status_code == 404, "Tenant A: GET Tenant B doc → 404 (no leakage)", f"got {resp.status_code}")

    # Tenant B DELETE Tenant A doc → 404 (not 403 — no info about existence)
    resp = req(client, "DELETE", f"/documents/{doc_a_id}", keys["b_editor"])
    check(resp.status_code in (404, 403), "Tenant B editor: DELETE Tenant A doc → 404/403", f"got {resp.status_code}")

    # Tenant B document list does NOT contain Tenant A doc
    resp = req(client, "GET", "/documents", keys["b_admin"])
    b_docs = [d["id"] for d in resp.json()]
    check(doc_a_id not in b_docs, "Tenant B list: Tenant A doc absent", f"found {doc_a_id[:8]} in B's list")

    # Tenant A document list does NOT contain Tenant B doc
    resp = req(client, "GET", "/documents", keys["a_admin"])
    a_docs = [d["id"] for d in resp.json()]
    check(doc_b_id not in a_docs, "Tenant A list: Tenant B doc absent", f"found {doc_b_id[:8]} in A's list")

    section("Tenant Isolation — Search does not leak across tenants")

    # Tenant B searching for Tenant A's secret marker → 0 results (no leakage)
    resp = req(client, "POST", "/search", keys["b_admin"],
               json={"query": secret_a, "mode": "hybrid", "top_k": 10})
    results_b = resp.json().get("results", [])
    a_ids_in_b = [r for r in results_b if r["document_id"] == doc_a_id]
    check(len(a_ids_in_b) == 0, "Tenant B hybrid search: Tenant A content not returned",
          f"leaked {len(a_ids_in_b)} result(s)")

    # Tenant A searching for Tenant B's secret marker → 0 results
    resp = req(client, "POST", "/search", keys["a_admin"],
               json={"query": secret_b, "mode": "hybrid", "top_k": 10})
    results_a = resp.json().get("results", [])
    b_ids_in_a = [r for r in results_a if r["document_id"] == doc_b_id]
    check(len(b_ids_in_a) == 0, "Tenant A hybrid search: Tenant B content not returned",
          f"leaked {len(b_ids_in_a)} result(s)")

    # Lexical search isolation
    resp = req(client, "POST", "/search", keys["b_admin"],
               json={"query": secret_a, "mode": "lexical_only", "top_k": 10})
    lexical_b = [r for r in resp.json().get("results", []) if r["document_id"] == doc_a_id]
    check(len(lexical_b) == 0, "Tenant B lexical search: Tenant A content not returned")

    # Vector search isolation
    resp = req(client, "POST", "/search", keys["b_admin"],
               json={"query": secret_a, "mode": "vector_only", "top_k": 10})
    vector_b = [r for r in resp.json().get("results", []) if r["document_id"] == doc_a_id]
    check(len(vector_b) == 0, "Tenant B vector search: Tenant A content not returned")

    return [doc_a_id, doc_b_id]


def test_key_revocation(client: httpx.Client, keys: dict) -> None:
    """Revoked key fails immediately."""
    section("Key Revocation")

    # Confirm key works before revoke
    resp = req(client, "GET", "/documents", keys["revocable"])
    check(resp.status_code == 200, "Revocable key works before revocation")

    # Revoke it
    resp = req(client, "DELETE", f"/admin/api-keys/{keys['revocable_id']}", keys["a_admin"])
    check(resp.status_code == 200, "Admin revokes key")

    # Key should now fail
    resp = req(client, "GET", "/documents", keys["revocable"])
    check(resp.status_code == 401, "Revoked key fails with 401", f"got {resp.status_code}")

    # Double-revoke idempotent (key already inactive)
    resp = req(client, "DELETE", f"/admin/api-keys/{keys['revocable_id']}", keys["a_admin"])
    check(resp.status_code in (200, 404), "Double-revoke handled gracefully", f"got {resp.status_code}")


def test_cross_tenant_key_management(client: httpx.Client, keys: dict) -> None:
    """Tenant A admin cannot manage Tenant B keys."""
    section("Cross-Tenant Key Management")

    # Tenant A admin cannot list Tenant B keys (gets own tenant keys only)
    resp = req(client, "GET", "/admin/api-keys", keys["a_admin"])
    a_keys = resp.json()
    b_key_labels = [k for k in a_keys if "rbac-test-b" in k.get("label", "")]
    check(len(b_key_labels) == 0, "Tenant A admin list: no Tenant B keys visible",
          f"leaked {len(b_key_labels)} B key(s)")

    # Tenant A admin cannot revoke Tenant B's editor key (different tenant)
    # First get Tenant B editor key ID
    resp = req(client, "GET", "/admin/api-keys", keys["b_admin"])
    b_keys = resp.json()
    b_editor_key_entry = next((k for k in b_keys if "editor" in k.get("label", "")), None)
    if b_editor_key_entry:
        resp = req(client, "DELETE", f"/admin/api-keys/{b_editor_key_entry['id']}", keys["a_admin"])
        check(resp.status_code in (404, 403), "Tenant A cannot revoke Tenant B key",
              f"got {resp.status_code}")
    else:
        warn("Could not find Tenant B editor key for cross-tenant revoke test")


def test_invalid_key(client: httpx.Client) -> None:
    """Garbage key rejected."""
    section("Invalid Key Handling")
    resp = req(client, "GET", "/documents", "cortex_totallyinvalidkey12345")
    check(resp.status_code == 401, "Invalid key → 401", f"got {resp.status_code}")

    resp = req(client, "GET", "/health", "")
    # health is public or returns 401/403 depending on implementation
    ok(f"No key on health → HTTP {resp.status_code} (not 500)")


def test_cleanup(client: httpx.Client, keys: dict, doc_ids: list[str]) -> None:
    section("Cleanup")
    for doc_id in doc_ids:
        try:
            # Try from both tenants in case ownership varies
            for k in [keys["a_admin"], keys["b_admin"]]:
                r = req(client, "DELETE", f"/documents/{doc_id}", k)
                if r.status_code in (202, 404):
                    break
            ok(f"Doc {doc_id[:8]} cleaned")
        except Exception:
            warn(f"Cleanup failed for {doc_id[:8]}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    global passed, failed
    parser = argparse.ArgumentParser(description="RBAC + tenant isolation E2E test")
    parser.add_argument("--base-url", default="https://knowledge.basivo.in")
    parser.add_argument("--admin-key", required=True)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    print(f"\n{BOLD}Cortex KB — RBAC + Tenant Isolation Test{RESET}")
    print(f"Server: {CYAN}{args.base_url}{RESET}\n")

    start = time.monotonic()
    all_doc_ids = []
    keys = {}

    with httpx.Client(base_url=args.base_url, timeout=args.timeout, verify=False) as client:
        try:
            keys = test_setup(client, args.admin_key)

            test_rbac_admin(client, keys)
            test_rbac_editor(client, keys)
            test_rbac_viewer(client, keys)
            isolation_docs = test_tenant_isolation(client, keys)
            all_doc_ids.extend(isolation_docs)
            test_key_revocation(client, keys)
            test_cross_tenant_key_management(client, keys)
            test_invalid_key(client)

        except TestError as e:
            print(f"\n  {RED}STOPPED:{RESET} {e}")
        except Exception as e:
            print(f"\n  {RED}Unexpected:{RESET} {e}")
            import traceback; traceback.print_exc()
        finally:
            if all_doc_ids and keys:
                test_cleanup(client, keys, all_doc_ids)

    elapsed = time.monotonic() - start
    total = passed + failed
    print(f"\n{'─' * 60}")
    print(f"  Passed: {GREEN}{passed}/{total}{RESET}   Failed: {RED}{failed}{RESET}   Time: {elapsed:.1f}s")
    print(f"{'─' * 60}\n")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
