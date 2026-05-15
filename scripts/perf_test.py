#!/usr/bin/env python3
"""
Cortex KB — Performance & Extended Integration Test
Tests: latency, throughput, concurrency, large docs, edge cases, search quality.

Usage:
    uv run python scripts/perf_test.py --base-url https://knowledge.basivo.in --api-key cortex_xxx
"""
import argparse
import asyncio
import statistics
import sys
import time
import uuid
from typing import Optional

import httpx

# ── Config ────────────────────────────────────────────────────────────────────
DEFAULT_BASE = "https://knowledge.basivo.in"
PIPELINE_TIMEOUT = 120
POLL_INTERVAL = 2

# ANSI
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"
DIM = "\033[2m"

# ── Test Documents ─────────────────────────────────────────────────────────────
SMALL_DOC = """Machine Learning Fundamentals

Supervised learning trains models on labeled data. The model learns to map
inputs to outputs by minimizing a loss function. Common algorithms include
linear regression, decision trees, and neural networks.

Unsupervised learning discovers hidden patterns in unlabeled data. Clustering
algorithms group similar data points. Dimensionality reduction techniques like
PCA compress high-dimensional data into lower-dimensional representations.

Reinforcement learning trains agents through reward signals. The agent explores
an environment, takes actions, and learns to maximize cumulative reward over time.
"""

MEDIUM_DOC = (SMALL_DOC + "\n\n") * 8  # ~2000 tokens

LARGE_DOC = ("""
Knowledge Management Systems in Enterprise Environments

Knowledge management (KM) encompasses the strategies and processes organizations
use to create, capture, distribute, and effectively use knowledge assets. Modern
KM systems leverage artificial intelligence to automate knowledge extraction from
unstructured documents, emails, and communications.

Vector databases enable semantic search by representing text as high-dimensional
embeddings. Unlike traditional keyword search, semantic search understands context
and meaning, retrieving relevant results even when exact keywords don't match.

Retrieval Augmented Generation (RAG) combines vector search with large language
models. Documents are chunked, embedded, and stored in a vector database. At
query time, relevant chunks are retrieved and passed as context to an LLM,
which generates accurate, grounded responses.

Hybrid search combines vector similarity with full-text search (BM25/TF-IDF),
achieving better results than either approach alone. The scores are normalized
and weighted to produce a final ranking.

Enterprise KB systems require robust access control, audit logging, multi-tenant
isolation, and compliance with data residency requirements. Document lifecycle
management includes versioning, expiry, and automated deletion workflows.
""" * 15)  # ~3000 tokens


# ── Helpers ───────────────────────────────────────────────────────────────────
class PerfError(Exception):
    pass


def section(title: str) -> None:
    print(f"\n{BOLD}{CYAN}── {title}{RESET}")


def ok(msg: str, detail: str = "") -> None:
    d = f"  {DIM}{detail}{RESET}" if detail else ""
    print(f"  {GREEN}✓{RESET}  {msg}{d}")


def fail(msg: str, detail: str = "") -> None:
    d = f"\n      {RED}{detail}{RESET}" if detail else ""
    print(f"  {RED}✗{RESET}  {msg}{d}")
    raise PerfError(msg)


def warn(msg: str, detail: str = "") -> None:
    d = f"  {DIM}{detail}{RESET}" if detail else ""
    print(f"  {YELLOW}⚠{RESET}  {msg}{d}")


def assert_status(resp: httpx.Response, expected: int, label: str) -> dict:
    if resp.status_code != expected:
        raise PerfError(f"{label}: expected {expected}, got {resp.status_code} — {resp.text[:200]}")
    return resp.json()


def upload_doc(client: httpx.Client, headers: dict, content: str, name: str) -> str:
    run_id = uuid.uuid4().hex[:8]
    fname = f"{name}_{run_id}.txt"
    resp = client.post(
        "/ingest/upload",
        files={"file": (fname, content.encode(), "text/plain")},
        headers=headers,
    )
    data = assert_status(resp, 202, f"Upload {name}")
    return data["document_id"]


def poll_pipeline(client: httpx.Client, headers: dict, doc_id: str, label: str = "") -> float:
    """Returns elapsed seconds until indexed."""
    start = time.monotonic()
    deadline = start + PIPELINE_TIMEOUT
    while time.monotonic() < deadline:
        resp = client.get(f"/status/{doc_id}", headers=headers)
        if resp.status_code == 404:
            time.sleep(POLL_INTERVAL)
            continue
        data = assert_status(resp, 200, "Status")
        overall = data.get("overall_status", "")
        if overall == "indexed":
            return time.monotonic() - start
        if "failed" in overall or overall == "error":
            stages = data.get("stages", {})
            fail(f"Pipeline failed [{label}]: {overall}", str(stages))
        time.sleep(POLL_INTERVAL)
    fail(f"Pipeline timeout [{label}] after {PIPELINE_TIMEOUT}s")
    return -1


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_health(client: httpx.Client) -> dict:
    section("Health & Backend Verification")
    resp = client.get("/health")
    data = assert_status(resp, 200, "Health")
    reg = data.get("registry", {})
    ok(f"Status: {data['status']}")
    ok(f"Parse:  {reg.get('parse_backend')}")
    ok(f"Embed:  {reg.get('embed_backend')} dim={reg.get('embed_dimension')}")
    ok(f"Vector: {reg.get('vector_backend')} mode={reg.get('search_mode')}")
    comps = data.get("components", {})
    for name, c in comps.items():
        status = c.get("status", "?")
        if status == "ok":
            ok(f"  {name}: ok")
        else:
            warn(f"  {name}: {status}")
    return reg


def test_upload_latency(client: httpx.Client, headers: dict) -> list[str]:
    section("Upload Latency (5 small docs)")
    doc_ids = []
    times = []
    for i in range(5):
        t0 = time.monotonic()
        doc_id = upload_doc(client, headers, SMALL_DOC + f"\n\nDoc {i}", f"perf_small_{i}")
        elapsed = (time.monotonic() - t0) * 1000
        times.append(elapsed)
        doc_ids.append(doc_id)
        ok(f"  Doc {i+1}: {elapsed:.0f}ms", f"id={doc_id[:8]}")

    ok(f"Avg upload latency: {statistics.mean(times):.0f}ms  "
       f"p95: {sorted(times)[int(len(times)*0.95)]:.0f}ms  "
       f"max: {max(times):.0f}ms")
    return doc_ids


def test_pipeline_throughput(client: httpx.Client, headers: dict, doc_ids: list[str]) -> None:
    section("Pipeline Throughput (5 docs parallel)")
    t0 = time.monotonic()
    times = []
    for doc_id in doc_ids:
        elapsed = poll_pipeline(client, headers, doc_id, label=doc_id[:8])
        times.append(elapsed)
        ok(f"  {doc_id[:8]}: {elapsed:.1f}s")

    total = time.monotonic() - t0
    ok(f"All indexed in {total:.1f}s  avg/doc={statistics.mean(times):.1f}s  "
       f"throughput={len(doc_ids)/total:.2f} docs/s")


def test_large_doc(client: httpx.Client, headers: dict) -> Optional[str]:
    section("Large Document Pipeline (~3000 tokens)")
    t0 = time.monotonic()
    run_id = uuid.uuid4().hex[:8]
    doc_id = upload_doc(client, headers, LARGE_DOC + f"\n\nRun: {run_id}", "perf_large")
    upload_ms = (time.monotonic() - t0) * 1000
    ok(f"Uploaded {len(LARGE_DOC):,} chars in {upload_ms:.0f}ms")

    t1 = time.monotonic()
    elapsed = poll_pipeline(client, headers, doc_id, label="large_doc")
    ok(f"Indexed in {elapsed:.1f}s")

    # Get chunk count
    resp = client.get(f"/documents/{doc_id}/chunks", headers=headers)
    data = assert_status(resp, 200, "Chunks")
    chunks = data if isinstance(data, list) else data.get("chunks", [])
    ok(f"Chunk count: {len(chunks)}  avg_tokens≈{sum(c.get('token_count',0) for c in chunks)//max(len(chunks),1)}")
    return doc_id


def test_search_latency(client: httpx.Client, headers: dict) -> None:
    section("Search Latency (20 queries × 3 modes)")
    queries = [
        "machine learning supervised unsupervised",
        "knowledge management enterprise systems",
        "vector database semantic search embeddings",
        "retrieval augmented generation RAG",
        "hybrid search BM25 ranking",
        "neural network training loss function",
        "document chunking tokenization",
        "access control multi-tenant isolation",
        "reinforcement learning reward agent",
        "dimensionality reduction clustering PCA",
    ]

    for mode in ["hybrid", "vector_only", "lexical_only"]:
        times = []
        for q in queries:
            t0 = time.monotonic()
            resp = client.get("/search", params={"q": q, "mode": mode, "top_k": 5}, headers=headers)
            elapsed = (time.monotonic() - t0) * 1000
            assert_status(resp, 200, f"Search {mode}")
            times.append(elapsed)

        p50 = statistics.median(times)
        p95 = sorted(times)[int(len(times) * 0.95)]
        mean = statistics.mean(times)
        ok(f"{mode:12s}  mean={mean:.0f}ms  p50={p50:.0f}ms  p95={p95:.0f}ms  max={max(times):.0f}ms")

        # SLA check
        if p95 > 2000:
            warn(f"  p95 {p95:.0f}ms exceeds 2s SLA")
        elif p95 > 1000:
            warn(f"  p95 {p95:.0f}ms above 1s — acceptable but watch")


def test_search_quality(client: httpx.Client, headers: dict) -> None:
    section("Search Quality (relevance check)")
    cases = [
        ("machine learning supervised", "machine learning"),
        ("semantic vector embedding similarity", "vector"),
        ("knowledge management enterprise", "knowledge"),
        ("RAG retrieval augmented generation", "retrieval"),
    ]
    hits = 0
    for query, expected_keyword in cases:
        resp = client.get("/search", params={"q": query, "mode": "hybrid", "top_k": 3}, headers=headers)
        data = assert_status(resp, 200, "Search quality")
        results = data.get("results", [])
        if results and expected_keyword.lower() in results[0]["text"].lower():
            ok(f"  '{query[:40]}' → top result contains '{expected_keyword}'",
               f"score={results[0]['score']:.4f}")
            hits += 1
        else:
            warn(f"  '{query[:40]}' → top result missing '{expected_keyword}'",
                 f"got: {results[0]['text'][:60] if results else 'no results'}")

    ok(f"Relevance: {hits}/{len(cases)} queries returned relevant top result")


def test_concurrent_searches(client: httpx.Client, headers: dict) -> None:
    section("Concurrent Search Stress (10 parallel via threading)")
    import threading

    results = []
    errors = []

    def search_worker(i: int) -> None:
        try:
            t0 = time.monotonic()
            resp = client.get(
                "/search",
                params={"q": f"machine learning knowledge vector embedding {i}", "mode": "hybrid", "top_k": 5},
                headers=headers,
            )
            elapsed = (time.monotonic() - t0) * 1000
            assert_status(resp, 200, f"Concurrent search {i}")
            results.append(elapsed)
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=search_worker, args=(i,)) for i in range(10)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = (time.monotonic() - t0) * 1000

    if errors:
        warn(f"{len(errors)} errors in concurrent test", str(errors[0]))
    ok(f"10 concurrent searches in {total:.0f}ms  "
       f"avg={statistics.mean(results):.0f}ms  max={max(results):.0f}ms  "
       f"errors={len(errors)}")


def test_edge_cases(client: httpx.Client, headers: dict) -> None:
    section("Edge Cases")

    # Empty search query
    resp = client.get("/search", params={"q": "", "mode": "hybrid"}, headers=headers)
    if resp.status_code in (200, 422):
        ok("Empty query handled", f"HTTP {resp.status_code}")
    else:
        warn("Empty query unexpected response", f"HTTP {resp.status_code}")

    # Very long query
    long_q = "knowledge " * 100
    resp = client.get("/search", params={"q": long_q, "mode": "hybrid", "top_k": 5}, headers=headers)
    if resp.status_code == 200:
        ok("Long query (1000 chars) handled", f"HTTP {resp.status_code}")
    else:
        warn("Long query failed", f"HTTP {resp.status_code}")

    # Invalid doc_id
    resp = client.get("/documents/00000000-0000-0000-0000-000000000000", headers=headers)
    if resp.status_code == 404:
        ok("Invalid doc_id returns 404")
    else:
        warn("Invalid doc_id unexpected", f"HTTP {resp.status_code}")

    # Unsupported file type
    resp = client.post(
        "/ingest/upload",
        files={"file": ("test.xyz", b"binary data", "application/octet-stream")},
        headers=headers,
    )
    if resp.status_code in (400, 415, 422):
        ok("Unsupported file type rejected", f"HTTP {resp.status_code}")
    else:
        warn("Unsupported file type not rejected", f"HTTP {resp.status_code} {resp.text[:100]}")

    # top_k boundary
    resp = client.get("/search", params={"q": "test", "mode": "hybrid", "top_k": 1}, headers=headers)
    assert_status(resp, 200, "top_k=1")
    ok("top_k=1 works")

    resp = client.get("/search", params={"q": "test", "mode": "hybrid", "top_k": 50}, headers=headers)
    if resp.status_code == 200:
        ok("top_k=50 works")
    else:
        warn("top_k=50 rejected", f"HTTP {resp.status_code}")


def test_cleanup(client: httpx.Client, headers: dict, doc_ids: list[str]) -> None:
    section("Cleanup (delete test docs)")
    for doc_id in doc_ids:
        resp = client.delete(f"/documents/{doc_id}", headers=headers)
        if resp.status_code in (202, 404):
            ok(f"  {doc_id[:8]} deleted")
        else:
            warn(f"  {doc_id[:8]} delete failed", f"HTTP {resp.status_code}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Cortex KB performance + extended integration test")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--skip-cleanup", action="store_true", help="Leave test docs for manual inspection")
    args = parser.parse_args()

    print(f"\n{BOLD}Cortex KB — Performance & Extended Integration Test{RESET}")
    print(f"Server: {CYAN}{args.base_url}{RESET}\n")

    headers = {"X-Api-Key": args.api_key}
    passed = 0
    failed = 0
    all_doc_ids: list[str] = []

    start = time.monotonic()

    with httpx.Client(
        base_url=args.base_url,
        timeout=args.timeout,
        verify=False,  # skip SSL verify for self-signed certs
    ) as client:
        tests = [
            ("Health & Backends",       lambda: test_health(client)),
            ("Upload Latency",          lambda: test_upload_latency(client, headers)),
            ("Pipeline Throughput",     None),   # depends on upload result
            ("Large Document",          lambda: test_large_doc(client, headers)),
            ("Search Latency",          lambda: test_search_latency(client, headers)),
            ("Search Quality",          lambda: test_search_quality(client, headers)),
            ("Concurrent Search",       lambda: test_concurrent_searches(client, headers)),
            ("Edge Cases",              lambda: test_edge_cases(client, headers)),
        ]

        try:
            # Health
            test_health(client)
            passed += 1

            # Upload latency → get doc_ids
            small_doc_ids = test_upload_latency(client, headers)
            all_doc_ids.extend(small_doc_ids)
            passed += 1

            # Pipeline throughput (uses small_doc_ids)
            test_pipeline_throughput(client, headers, small_doc_ids)
            passed += 1

            # Large doc
            large_id = test_large_doc(client, headers)
            if large_id:
                all_doc_ids.append(large_id)
            passed += 1

            # Search latency
            test_search_latency(client, headers)
            passed += 1

            # Search quality
            test_search_quality(client, headers)
            passed += 1

            # Concurrent search
            test_concurrent_searches(client, headers)
            passed += 1

            # Edge cases
            test_edge_cases(client, headers)
            passed += 1

        except PerfError as e:
            failed += 1
            print(f"\n  {RED}FAILED:{RESET} {e}")
        except Exception as e:
            failed += 1
            print(f"\n  {RED}Unexpected:{RESET} {e}")
            import traceback
            traceback.print_exc()

        finally:
            if not args.skip_cleanup:
                try:
                    test_cleanup(client, headers, all_doc_ids)
                except Exception:
                    pass

    elapsed = time.monotonic() - start
    print(f"\n{'─' * 60}")
    print(f"  Passed: {GREEN}{passed}{RESET}   Failed: {RED}{failed}{RESET}   Time: {elapsed:.1f}s")
    print(f"{'─' * 60}\n")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
