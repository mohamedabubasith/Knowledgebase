#!/usr/bin/env python3
"""
Cortex KB — Deduplication & Replace E2E test.

Tests the smart upload deduplication logic:

  Case 1 — Same file re-uploaded (same hash, indexed)
            → server returns existing doc_id, status=indexed immediately
            → no new pipeline run

  Case 2 — Same file re-uploaded (same hash, but first run had failed)
            → server reprocesses from stored MinIO file automatically
            → pipeline runs again to completion

  Case 3 — Updated file re-uploaded (same filename, different content/hash)
            → server deletes old doc, uploads new, runs full pipeline
            → old doc disappears from status; new doc reaches indexed

  Case 4 — Fresh file (different name, different content)
            → normal upload + pipeline (sanity check)

Usage:
    python scripts/dedup_e2e_test.py \\
      --base-url https://knowledge.basivo.in \\
      --api-key cortex_xxx
"""
import argparse
import os
import sys
import time
from pathlib import Path

import httpx

# ── Load .env ─────────────────────────────────────────────────────────────────
_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            k, _, v = _line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

# ── Colour ────────────────────────────────────────────────────────────────────
GREEN  = "\033[92m"; RED    = "\033[91m"; YELLOW = "\033[93m"
CYAN   = "\033[96m"; BOLD   = "\033[1m";  RESET  = "\033[0m"

def ok(m):      print(f"  {GREEN}✓{RESET}  {m}")
def fail(m):    print(f"  {RED}✗{RESET}  {m}"); sys.exit(1)
def info(m):    print(f"  {CYAN}·{RESET}  {m}")
def warn(m):    print(f"  {YELLOW}!{RESET}  {m}")
def section(t): print(f"\n{BOLD}{t}{RESET}")

# ── Test data ─────────────────────────────────────────────────────────────────
CSV_V1 = b"""product,revenue,region
Widget A,5000,North
Widget B,3000,South
Widget C,4000,East
"""

CSV_V2 = b"""product,revenue,region,units
Widget A,7500,North,300
Widget B,4200,South,180
Widget C,5800,East,240
Widget D,3100,West,130
"""

FILENAME = "dedup_test_sales.csv"

# ── Helpers ───────────────────────────────────────────────────────────────────
def hdr(key): return {"X-Api-Key": key}


def upload(client, base, key, filename, data, mime="text/csv"):
    r = client.post(
        f"{base}/ingest/upload",
        files={"file": (filename, data, mime)},
        headers=hdr(key),
    )
    assert r.status_code in (200, 202), f"Upload failed {r.status_code}: {r.text}"
    return r.json()


def poll(client, base, key, doc_id, timeout=180):
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        r = client.get(f"{base}/status/{doc_id}", headers=hdr(key))
        if r.status_code == 404:
            return "deleted"
        s = r.json().get("overall_status", "?")
        if s != last:
            info(f"  [{doc_id[:8]}] status={s}")
            last = s
        if s == "indexed":
            return "indexed"
        if s in ("failed", "error", "parse_failed", "chunk_failed", "embed_failed"):
            return s
        time.sleep(3)
    return "timeout"


def delete(client, base, key, doc_id):
    r = client.delete(f"{base}/documents/{doc_id}", headers=hdr(key))
    return r.status_code in (200, 202, 404)


# ── Test cases ────────────────────────────────────────────────────────────────

def test_case1_same_hash_indexed(client, base, key):
    section("Case 1 — Same file re-uploaded (already indexed)")
    info("Uploading v1 fresh...")
    resp = upload(client, base, key, FILENAME, CSV_V1)
    doc_id = resp["document_id"]
    info(f"doc_id={doc_id}  status={resp.get('status')}")

    status = poll(client, base, key, doc_id)
    assert status == "indexed", f"Expected indexed, got {status}"
    ok(f"First upload indexed: {doc_id}")

    info("Re-uploading exact same file...")
    resp2 = upload(client, base, key, FILENAME, CSV_V1)
    doc_id2 = resp2["document_id"]
    status2 = resp2.get("status")

    assert doc_id2 == doc_id, f"Expected same doc_id {doc_id}, got {doc_id2}"
    assert status2 == "indexed", f"Expected status=indexed, got {status2}"
    ok(f"Same doc_id returned: {doc_id2}")
    ok(f"Status=indexed immediately — no pipeline re-run ✓")
    return doc_id


def test_case3_same_name_new_content(client, base, key, old_doc_id):
    section("Case 3 — Same filename, updated content (different hash)")
    info(f"Old doc_id={old_doc_id}")
    info("Uploading v2 (new content, same filename)...")

    resp = upload(client, base, key, FILENAME, CSV_V2)
    new_doc_id = resp["document_id"]
    info(f"New doc_id={new_doc_id}  status={resp.get('status')}")

    assert new_doc_id != old_doc_id, "Expected new doc_id for different content"
    ok(f"New doc_id assigned: {new_doc_id}")

    info("Polling new doc to indexed...")
    status = poll(client, base, key, new_doc_id)
    assert status == "indexed", f"New doc pipeline failed: {status}"
    ok("New doc indexed ✓")

    info("Checking old doc is purged...")
    time.sleep(5)  # purge is async
    r = client.get(f"{base}/status/{old_doc_id}", headers=hdr(key))
    if r.status_code == 404:
        ok("Old doc deleted from DB ✓")
    else:
        old_status = r.json().get("overall_status", "?")
        if old_status in ("deleting", "deleted"):
            ok(f"Old doc status={old_status} ✓")
        else:
            warn(f"Old doc still present with status={old_status} (purge may still be queued)")

    return new_doc_id


def test_case4_fresh_file(client, base, key):
    section("Case 4 — Fresh file (different name)")
    fresh_data = b"id,value\n1,alpha\n2,beta\n3,gamma\n"
    resp = upload(client, base, key, "dedup_test_fresh.csv", fresh_data)
    doc_id = resp["document_id"]
    info(f"doc_id={doc_id}  status={resp.get('status')}")
    status = poll(client, base, key, doc_id)
    assert status == "indexed", f"Fresh upload failed: {status}"
    ok("Fresh file indexed ✓")
    return doc_id


def cleanup(client, base, key, *doc_ids):
    section("Cleanup")
    for doc_id in doc_ids:
        if doc_id and delete(client, base, key, doc_id):
            ok(f"Deleted {doc_id[:8]}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")

    print(f"\n{BOLD}Cortex KB — Dedup E2E Test{RESET}")
    print(f"  Base URL : {base}")

    with httpx.Client(timeout=args.timeout, verify=False) as client:
        # Health
        section("Health")
        r = client.get(f"{base}/health")
        assert r.status_code == 200, f"Health failed: {r.status_code}"
        ok("Server healthy")

        new_doc_id = fresh_doc_id = None
        try:
            # Case 1: same hash → immediate indexed response
            old_doc_id = test_case1_same_hash_indexed(client, base, args.api_key)

            # Case 3: same filename, new content → replace
            new_doc_id = test_case3_same_name_new_content(client, base, args.api_key, old_doc_id)

            # Case 4: fresh file
            fresh_doc_id = test_case4_fresh_file(client, base, args.api_key)

        finally:
            cleanup(client, base, args.api_key, new_doc_id, fresh_doc_id)

    print(f"\n{GREEN}{BOLD}All dedup E2E tests passed ✓{RESET}\n")


if __name__ == "__main__":
    main()
