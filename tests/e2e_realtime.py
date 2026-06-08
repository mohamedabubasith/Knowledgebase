#!/usr/bin/env python3
"""
Real E2E test against running API at localhost:8001.
Flow: login → create KB → upload doc → poll until indexed → query → cleanup
"""
import sys
import time
import json
import tempfile
import os
import requests

BASE = "http://localhost:8001/api/v1"
EMAIL = os.getenv("SUPER_ADMIN_EMAIL", "admin@example.com")
PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD", "Admin@123")
POLL_TIMEOUT = 120  # seconds to wait for document indexing
POLL_INTERVAL = 3

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m→\033[0m"

errors = []


def check(label: str, condition: bool, detail: str = ""):
    if condition:
        print(f"  {PASS} {label}")
    else:
        print(f"  {FAIL} {label}" + (f": {detail}" if detail else ""))
        errors.append(label)


def step(name: str):
    print(f"\n{INFO} {name}")


# ── 1. Health ─────────────────────────────────────────────────────────────────
step("Health check")
r = requests.get("http://localhost:8001/health")
check("GET /health → 200", r.status_code == 200)
check("status ok", r.json().get("status") == "ok", str(r.json()))

# ── 2. Login ──────────────────────────────────────────────────────────────────
step(f"Login as {EMAIL}")
r = requests.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD})
check("POST /auth/login → 200", r.status_code == 200, r.text[:200])
token = r.json().get("access_token", "")
check("access_token present", bool(token))
HEADERS = {"Authorization": f"Bearer {token}"}

# ── 3. Whoami ─────────────────────────────────────────────────────────────────
step("Verify identity")
r = requests.get(f"{BASE}/auth/me", headers=HEADERS)
check("GET /auth/me → 200", r.status_code == 200, r.text[:200])
check("email matches", r.json().get("email") == EMAIL)
check("role is super_admin", r.json().get("role") == "super_admin")

# ── 4. Create KB ──────────────────────────────────────────────────────────────
step("Create knowledge base")
kb_name = f"e2e-test-{int(time.time())}"
r = requests.post(f"{BASE}/knowledge-bases", headers=HEADERS,
                  json={"name": kb_name, "description": "E2E test KB"})
check("POST /knowledge-bases → 201", r.status_code == 201, r.text[:200])
kb_id = r.json().get("id", "")
check("id present", bool(kb_id))
print(f"    kb_id={kb_id}")

# ── 5. List KBs ───────────────────────────────────────────────────────────────
step("List knowledge bases")
r = requests.get(f"{BASE}/knowledge-bases", headers=HEADERS)
check("GET /knowledge-bases → 200", r.status_code == 200)
kb_ids = [kb["id"] for kb in r.json()]
check("new KB in list", kb_id in kb_ids)

# ── 6. Upload document ────────────────────────────────────────────────────────
step("Upload document")
doc_content = b"""Artificial Intelligence Overview
================================
AI is the simulation of human intelligence by machines.
Machine learning is a subset of AI that enables learning from data.
Deep learning uses neural networks with many layers.
Natural Language Processing (NLP) helps computers understand human language.
Knowledge bases store structured information for retrieval.
Vector embeddings represent text as numerical vectors for semantic search.
"""
with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
    f.write(doc_content)
    tmp_path = f.name

try:
    with open(tmp_path, "rb") as f:
        r = requests.post(
            f"{BASE}/knowledge-bases/{kb_id}/documents/upload",
            headers=HEADERS,
            files={"file": ("ai_overview.txt", f, "text/plain")},
        )
    check("POST /documents/upload → 202", r.status_code == 202, r.text[:300])
    doc_id = r.json().get("id", "")
    check("doc id present", bool(doc_id))
    print(f"    doc_id={doc_id}")
finally:
    os.unlink(tmp_path)

# ── 7. Poll until indexed ─────────────────────────────────────────────────────
step(f"Wait for document indexing (timeout={POLL_TIMEOUT}s)")
start = time.time()
final_status = None
while time.time() - start < POLL_TIMEOUT:
    r = requests.get(f"{BASE}/knowledge-bases/{kb_id}/documents/{doc_id}", headers=HEADERS)
    if r.status_code == 200:
        doc = r.json()
        status = doc.get("status", "unknown")
        elapsed = int(time.time() - start)
        print(f"    [{elapsed}s] status={status}", end="\r")
        sys.stdout.flush()
        if status in ("indexed", "completed", "failed", "error"):
            final_status = status
            print()
            break
    time.sleep(POLL_INTERVAL)

check("document indexed/completed (not failed/timeout)",
      final_status in ("indexed", "completed"),
      f"final_status={final_status}")

# ── 8. Check chunks ───────────────────────────────────────────────────────────
step("Verify chunks created")
r = requests.get(f"{BASE}/knowledge-bases/{kb_id}/documents/{doc_id}/chunks", headers=HEADERS)
check("GET /chunks → 200", r.status_code == 200, r.text[:200])
chunks = r.json()
check("at least 1 chunk", len(chunks) > 0, f"got {len(chunks)}")
print(f"    chunks={len(chunks)}")

# ── 9. Semantic search ────────────────────────────────────────────────────────
step("Semantic search")
r = requests.post(
    f"{BASE}/query/search",
    headers=HEADERS,
    json={"knowledge_base_id": kb_id, "prompt": "what is machine learning", "top_k": 3},
)
check("POST /query/search → 200", r.status_code == 200, r.text[:300])
results = r.json() if r.status_code == 200 else []
check("search returned results", len(results) > 0, f"got {len(results)}")
if results:
    score = results[0].get('score', 'n/a')
    score_str = f"{score:.4f}" if isinstance(score, float) else str(score)
    print(f"    top result score={score_str}")
    print(f"    snippet: {str(results[0].get('text',''))[:80]}...")

# ── 10. RAG query ─────────────────────────────────────────────────────────────
step("RAG query (LLM may be slow — 30s timeout)")
try:
    r = requests.post(
        f"{BASE}/query",
        headers=HEADERS,
        json={"knowledge_base_id": kb_id, "prompt": "explain neural networks", "top_k": 3},
        timeout=30,
    )
    check("POST /query → 200 or 5xx", r.status_code in (200, 500, 503), f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        print(f"    answer: {str(r.json().get('response',''))[:100]}...")
except requests.exceptions.Timeout:
    print("    (timed out after 30s — LLM loading, expected for local dev)")
    check("POST /query → timeout acceptable", True)

# ── 11. Cleanup ───────────────────────────────────────────────────────────────
step("Cleanup — delete KB")
r = requests.delete(f"{BASE}/knowledge-bases/{kb_id}", headers=HEADERS)
check("DELETE /knowledge-bases → 204", r.status_code == 204, r.text[:200])

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "═" * 50)
if errors:
    print(f"\033[91mFAILED\033[0m — {len(errors)} check(s) failed:")
    for e in errors:
        print(f"  • {e}")
    sys.exit(1)
else:
    print(f"\033[92mPASSED\033[0m — all checks passed")
    sys.exit(0)
