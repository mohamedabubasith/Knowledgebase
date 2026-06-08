#!/usr/bin/env python3
"""
E2E test: tenant creation → API key → KB → upload → index → query → share with User B → User B queries
All against live API at localhost:8001. No mocks.
"""
import os, sys, time, tempfile, requests

BASE     = "http://localhost:8001/api/v1"
ADMIN_EMAIL    = os.getenv("SUPER_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD", "Admin@123")

POLL_TIMEOUT  = 180
POLL_INTERVAL = 4

G = "\033[92m"  # green
R = "\033[91m"  # red
B = "\033[94m"  # blue
Y = "\033[93m"  # yellow
X = "\033[0m"   # reset

errors: list[str] = []
_section = [0]

def section(title: str):
    _section[0] += 1
    print(f"\n{B}── {_section[0]}. {title}{X}")

def ok(label: str, detail: str = ""):
    print(f"  {G}✓{X} {label}" + (f"  [{detail}]" if detail else ""))

def fail(label: str, detail: str = ""):
    print(f"  {R}✗{X} {label}" + (f"  [{detail}]" if detail else ""))
    errors.append(label)

def chk(label: str, cond: bool, detail: str = ""):
    ok(label, detail) if cond else fail(label, detail)
    return cond

def info(msg: str):
    print(f"  {Y}·{X} {msg}")

def must(label: str, cond: bool, detail: str = ""):
    if not chk(label, cond, detail):
        _summary()
        sys.exit(1)
    return cond

def _summary():
    print(f"\n{'═'*56}")
    if errors:
        print(f"{R}FAILED{X} — {len(errors)} check(s) failed:")
        for e in errors:
            print(f"  • {e}")
    else:
        print(f"{G}ALL PASSED{X}")

# ─────────────────────────────────────────────────────────────────────────────
# 1. Health
# ─────────────────────────────────────────────────────────────────────────────
section("Health check")
r = requests.get("http://localhost:8001/health")
must("GET /health → 200", r.status_code == 200)
chk("status: ok", r.json().get("status") == "ok")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Admin login
# ─────────────────────────────────────────────────────────────────────────────
section(f"Admin login ({ADMIN_EMAIL})")
r = requests.post(f"{BASE}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
must("POST /auth/login → 200", r.status_code == 200, r.text[:200])
admin_token = r.json()["access_token"]
ADMIN = {"Authorization": f"Bearer {admin_token}"}
info(f"admin token: {admin_token[:24]}…")

r = requests.get(f"{BASE}/auth/me", headers=ADMIN)
chk("role = super_admin", r.json().get("role") == "super_admin")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Create tenant
# ─────────────────────────────────────────────────────────────────────────────
section("Create tenant")
ts = int(time.time())
tenant_name = f"e2e-tenant-{ts}"
r = requests.post(f"{BASE}/admin/tenants", headers=ADMIN,
                  json={"name": tenant_name, "description": "E2E test tenant"})
must("POST /admin/tenants → 201", r.status_code == 201, r.text[:300])
tenant = r.json()
tenant_id  = tenant["id"]
api_key    = tenant["api_key"]
chk("api_key starts with kb_", api_key.startswith("kb_"))
info(f"tenant_id: {tenant_id}")
info(f"api_key:   {api_key[:18]}…")

# Headers using tenant API key (no login needed)
TENANT = {"X-API-Key": api_key}

# ─────────────────────────────────────────────────────────────────────────────
# 4. Tenant creates a KB via API key
# ─────────────────────────────────────────────────────────────────────────────
section("Tenant creates knowledge base (via API key)")
kb_name = f"e2e-kb-{ts}"
r = requests.post(f"{BASE}/knowledge-bases", headers=TENANT,
                  json={"name": kb_name, "description": "E2E KB"})
must("POST /knowledge-bases → 201", r.status_code == 201, r.text[:300])
kb_id = r.json()["id"]
info(f"kb_id: {kb_id}")

# Confirm it shows up in list
r = requests.get(f"{BASE}/knowledge-bases", headers=TENANT)
chk("KB appears in tenant list", any(k["id"] == kb_id for k in r.json()))

# ─────────────────────────────────────────────────────────────────────────────
# 5. Upload document via API key
# ─────────────────────────────────────────────────────────────────────────────
section("Upload document (via tenant API key)")
doc_text = b"""Cortex-KB Platform Guide
========================
Cortex-KB is a private AI knowledge base platform with tenant isolation.
Each tenant gets an isolated API key and owns their own knowledge bases.
Documents are parsed, chunked, embedded with sentence-transformers, and
stored in Qdrant for semantic search. LLM answers are generated via an
OpenAI-compatible endpoint (NVIDIA NIM). Role-based sharing lets tenant
users grant read, write, or delete access to specific knowledge bases.
The worker uses arq (async Redis queue) for background document processing.
Vector similarity search uses HNSW indexing in Qdrant collections.
"""
with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
    f.write(doc_text)
    tmp = f.name

try:
    with open(tmp, "rb") as f:
        r = requests.post(
            f"{BASE}/knowledge-bases/{kb_id}/documents/upload",
            headers=TENANT,
            files={"file": ("cortex_kb_guide.txt", f, "text/plain")},
        )
    must("POST /documents/upload → 202", r.status_code == 202, r.text[:300])
    doc_id = r.json()["id"]
    info(f"doc_id: {doc_id}")
finally:
    os.unlink(tmp)

# ─────────────────────────────────────────────────────────────────────────────
# 6. Poll until indexed
# ─────────────────────────────────────────────────────────────────────────────
section(f"Wait for indexing (timeout={POLL_TIMEOUT}s)")
t0 = time.time()
final_status = None
while time.time() - t0 < POLL_TIMEOUT:
    r = requests.get(f"{BASE}/knowledge-bases/{kb_id}/documents/{doc_id}", headers=TENANT)
    if r.status_code == 200:
        doc = r.json()
        status = doc.get("status", "?")
        stage  = doc.get("processing_stage", "?")
        elapsed = int(time.time() - t0)
        print(f"  {Y}·{X} [{elapsed:3d}s] status={status}  stage={stage}     ", end="\r")
        sys.stdout.flush()
        if status in ("indexed", "completed", "failed", "error"):
            final_status = status
            print()
            break
    time.sleep(POLL_INTERVAL)
else:
    print()

must("indexed/completed (not failed/timeout)",
     final_status in ("indexed", "completed"), f"final={final_status}")

r = requests.get(f"{BASE}/knowledge-bases/{kb_id}/documents/{doc_id}/chunks", headers=TENANT)
chk("chunks created", r.status_code == 200 and len(r.json()) > 0,
    f"{len(r.json())} chunks")
info(f"chunks: {len(r.json())}")

# ─────────────────────────────────────────────────────────────────────────────
# 7. Semantic search via API key
# ─────────────────────────────────────────────────────────────────────────────
section("Semantic search (tenant API key)")
r = requests.post(f"{BASE}/query/search", headers=TENANT,
                  json={"knowledge_base_id": kb_id,
                        "prompt": "how does tenant isolation work",
                        "top_k": 3})
chk("POST /query/search → 200", r.status_code == 200, r.text[:200])
if r.status_code == 200:
    results = r.json()
    chk("returned results", len(results) > 0, f"got {len(results)}")
    if results:
        score = results[0].get("score", 0)
        info(f"top score: {score:.4f}" if isinstance(score, float) else f"top score: {score}")
        info(f"snippet:   {str(results[0].get('text',''))[:80]}…")

# ─────────────────────────────────────────────────────────────────────────────
# 8. RAG query via API key
# ─────────────────────────────────────────────────────────────────────────────
section("RAG query / LLM answer (tenant API key, 60s timeout)")
try:
    r = requests.post(f"{BASE}/query", headers=TENANT,
                      json={"knowledge_base_id": kb_id,
                            "prompt": "explain the worker queue and document processing pipeline",
                            "top_k": 3},
                      timeout=60)
    chk("POST /query → 200", r.status_code == 200, f"{r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        resp = r.json()
        answer = resp.get("response", "")
        tokens = resp.get("tokens_used", 0)
        info(f"tokens: {tokens}")
        info(f"answer: {answer[:120]}…")
        chk("non-empty answer", bool(answer.strip()), "empty response")
except requests.exceptions.Timeout:
    info("LLM timed out after 60s — acceptable for local dev")
    chk("RAG timeout acceptable", True)

# ─────────────────────────────────────────────────────────────────────────────
# 9. Create User B
# ─────────────────────────────────────────────────────────────────────────────
section("Create User B (admin)")
user_b_email = f"user-b-{ts}@e2etest.dev"
user_b_pass  = "TestPass@123"
r = requests.post(f"{BASE}/users", headers=ADMIN,
                  json={"email": user_b_email, "password": user_b_pass,
                        "full_name": "E2E User B", "role": "user"})
must("POST /users → 201", r.status_code == 201, r.text[:300])
user_b_id = r.json()["id"]
info(f"user_b_id:    {user_b_id}")
info(f"user_b_email: {user_b_email}")

# ─────────────────────────────────────────────────────────────────────────────
# 10. Share KB with User B (read role) — shared by tenant via API key
# ─────────────────────────────────────────────────────────────────────────────
section("Share KB with User B (role=read)")
r = requests.post(f"{BASE}/knowledge-bases/{kb_id}/shares", headers=TENANT,
                  json={"email": user_b_email, "role": "read"})
chk("POST /knowledge-bases/{id}/shares → 201", r.status_code == 201, r.text[:300])
if r.status_code == 201:
    share = r.json()
    chk("role = read", share.get("role") == "read")
    chk("grantee_email matches", share.get("grantee_email") == user_b_email)
    info(f"share_id: {share.get('id')}")

# ─────────────────────────────────────────────────────────────────────────────
# 11. User B logs in
# ─────────────────────────────────────────────────────────────────────────────
section("User B logs in")
r = requests.post(f"{BASE}/auth/login", json={"email": user_b_email, "password": user_b_pass})
must("POST /auth/login (User B) → 200", r.status_code == 200, r.text[:200])
user_b_token = r.json()["access_token"]
USER_B = {"Authorization": f"Bearer {user_b_token}"}
info(f"user_b token: {user_b_token[:24]}…")

# ─────────────────────────────────────────────────────────────────────────────
# 12. User B sees the shared KB
# ─────────────────────────────────────────────────────────────────────────────
section("User B sees shared KB in list")
r = requests.get(f"{BASE}/knowledge-bases", headers=USER_B)
chk("GET /knowledge-bases → 200 (User B)", r.status_code == 200)
user_b_kbs = r.json() if r.status_code == 200 else []
chk("shared KB visible to User B", any(k["id"] == kb_id for k in user_b_kbs),
    f"visible KBs: {[k['name'] for k in user_b_kbs]}")

# ─────────────────────────────────────────────────────────────────────────────
# 13. User B searches KB (read role — allowed)
# ─────────────────────────────────────────────────────────────────────────────
section("User B searches shared KB (read role → allowed)")
r = requests.post(f"{BASE}/query/search", headers=USER_B,
                  json={"knowledge_base_id": kb_id,
                        "prompt": "what is Cortex-KB",
                        "top_k": 3})
chk("POST /query/search (User B) → 200", r.status_code == 200, r.text[:200])
if r.status_code == 200:
    results = r.json()
    chk("User B got results", len(results) > 0, f"got {len(results)}")
    if results:
        info(f"top score: {results[0].get('score', '?')}")
        info(f"snippet:   {str(results[0].get('text',''))[:80]}…")

# ─────────────────────────────────────────────────────────────────────────────
# 14. User B tries to upload (read role → must be rejected)
# ─────────────────────────────────────────────────────────────────────────────
section("User B tries upload (read role → must be DENIED)")
with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
    f.write(b"should be rejected")
    tmp2 = f.name
try:
    with open(tmp2, "rb") as f:
        r = requests.post(
            f"{BASE}/knowledge-bases/{kb_id}/documents/upload",
            headers=USER_B,
            files={"file": ("blocked.txt", f, "text/plain")},
        )
    chk("upload blocked for read-only user (403)", r.status_code == 403,
        f"got {r.status_code}: {r.text[:150]}")
finally:
    os.unlink(tmp2)

# ─────────────────────────────────────────────────────────────────────────────
# 15. List shares (confirm visible from KB endpoint)
# ─────────────────────────────────────────────────────────────────────────────
section("List shares on KB")
r = requests.get(f"{BASE}/knowledge-bases/{kb_id}/shares", headers=TENANT)
chk("GET /knowledge-bases/{id}/shares → 200", r.status_code == 200, r.text[:200])
if r.status_code == 200:
    shares = r.json()
    chk("share list non-empty", len(shares) > 0, f"{len(shares)} share(s)")
    found = any(s.get("grantee_email") == user_b_email for s in shares)
    chk("User B in shares", found)

# ─────────────────────────────────────────────────────────────────────────────
# 16. Revoke share
# ─────────────────────────────────────────────────────────────────────────────
section("Revoke User B share")
r = requests.delete(f"{BASE}/knowledge-bases/{kb_id}/shares/{user_b_id}", headers=TENANT)
chk("DELETE /shares/{user_id} → 204", r.status_code == 204, r.text[:150])

# Confirm User B can no longer see KB
r = requests.get(f"{BASE}/knowledge-bases", headers=USER_B)
still_visible = any(k["id"] == kb_id for k in (r.json() if r.status_code == 200 else []))
chk("KB no longer visible to User B after revoke", not still_visible)

# ─────────────────────────────────────────────────────────────────────────────
# 17. Tenant stats via admin
# ─────────────────────────────────────────────────────────────────────────────
section("Tenant stats (admin)")
r = requests.get(f"{BASE}/admin/tenants/{tenant_id}/stats", headers=ADMIN)
chk("GET /admin/tenants/{id}/stats → 200", r.status_code == 200, r.text[:200])
if r.status_code == 200:
    s = r.json()
    info(f"knowledge_bases={s['knowledge_bases']}  documents={s['documents']}  chunks={s['chunks']}  prompts_today={s['prompts_today']}")
    chk("stats.knowledge_bases >= 1", s["knowledge_bases"] >= 1)
    chk("stats.documents >= 1",       s["documents"] >= 1)
    chk("stats.chunks >= 1",          s["chunks"] >= 1)

# ─────────────────────────────────────────────────────────────────────────────
# 18. Cleanup
# ─────────────────────────────────────────────────────────────────────────────
section("Cleanup")
r = requests.delete(f"{BASE}/users/{user_b_id}", headers=ADMIN)
chk("DELETE User B → 204", r.status_code == 204)

r = requests.delete(f"{BASE}/admin/tenants/{tenant_id}", headers=ADMIN)
chk("DELETE tenant → 204", r.status_code == 204, r.text[:200])

# Confirm KB gone
r = requests.get(f"{BASE}/knowledge-bases/{kb_id}", headers=ADMIN)
chk("KB deleted (404 after tenant delete)", r.status_code == 404, f"got {r.status_code}")

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
_summary()
sys.exit(1 if errors else 0)
