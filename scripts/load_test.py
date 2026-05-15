#!/usr/bin/env python3
"""
Cortex KB — Async Load Test
Ramps concurrent users, measures p50/p95/p99, reports error rate.
Designed to find the breaking point that causes server crashes/restarts.

Usage:
    # Quick search-only load test
    python scripts/load_test.py --base-url https://knowledge.basivo.in --api-key cortex_xxx

    # Full test including uploads (slower, heavier)
    python scripts/load_test.py --base-url https://knowledge.basivo.in --api-key cortex_xxx --with-uploads

    # Ramp test: find breaking point
    python scripts/load_test.py --base-url https://knowledge.basivo.in --api-key cortex_xxx --ramp

    # Sustained spike (hold N concurrent users for duration)
    python scripts/load_test.py --base-url https://knowledge.basivo.in --api-key cortex_xxx --spike 50 --duration 60
"""
import argparse
import asyncio
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import httpx

# ── ANSI ───────────────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def c(color: str, s: str) -> str:
    return f"{color}{s}{RESET}"

# ── Result bucket ──────────────────────────────────────────────────────────────
@dataclass
class Results:
    label: str
    latencies: list[float] = field(default_factory=list)
    errors: list[str]      = field(default_factory=list)
    status_codes: list[int] = field(default_factory=list)

    def add(self, latency_ms: float, status: int, error: Optional[str] = None) -> None:
        self.latencies.append(latency_ms)
        self.status_codes.append(status)
        if error:
            self.errors.append(error)

    def report(self) -> None:
        n = len(self.latencies)
        if n == 0:
            print(f"  {self.label}: no data")
            return
        ok  = sum(1 for s in self.status_codes if s < 400)
        err = n - ok
        rate = err / n * 100
        s_sorted = sorted(self.latencies)
        p50  = statistics.median(s_sorted)
        p95  = s_sorted[int(0.95 * n)]
        p99  = s_sorted[int(0.99 * n)]
        mean = statistics.mean(s_sorted)
        color = RED if rate > 5 else (YELLOW if rate > 1 else GREEN)
        print(
            f"  {c(BOLD, self.label):<32} "
            f"n={n:>5}  "
            f"ok={ok:>5}  "
            f"{c(color, f'err={err}({rate:.1f}%)'):<25}  "
            f"mean={mean:>6.0f}ms  "
            f"p50={p50:>6.0f}ms  "
            f"p95={p95:>6.0f}ms  "
            f"p99={p99:>6.0f}ms"
        )
        if self.errors:
            unique = list(dict.fromkeys(self.errors))[:3]
            for e in unique:
                print(f"    {c(RED, '✗')} {e}")

# ── Sample documents ───────────────────────────────────────────────────────────
SAMPLE_DOCS = [
    ("sample_ml.txt", b"""Machine Learning Fundamentals

Supervised learning trains models on labeled data. The model learns to map
inputs to outputs by minimizing a loss function. Common algorithms include
linear regression, decision trees, random forests, and neural networks.

Unsupervised learning discovers patterns in unlabeled data. Clustering
algorithms like k-means and DBSCAN group similar data points. Dimensionality
reduction techniques like PCA compress high-dimensional data.

Deep learning uses multi-layer neural networks. Convolutional networks excel
at image recognition. Transformers dominate natural language processing.
Transfer learning applies pre-trained models to new tasks.

Gradient descent optimizes model parameters by iteratively moving in the
direction of steepest loss decrease. Learning rate controls step size.
Batch normalization and dropout prevent overfitting.
""", "text/plain"),
    ("sample_nlp.txt", b"""Natural Language Processing Overview

Tokenization splits text into words or subwords. Byte-pair encoding (BPE)
is used by GPT models. WordPiece is used by BERT. SentencePiece handles
multilingual tokenization without language-specific rules.

Word embeddings map words to dense vectors. Word2Vec uses skip-gram and
CBOW architectures. GloVe uses global co-occurrence statistics. FastText
handles out-of-vocabulary words using character n-grams.

Attention mechanisms allow models to focus on relevant input parts.
Self-attention computes relationships between all token pairs. Multi-head
attention learns different relationship types in parallel.

BERT pre-trains on masked language modeling and next sentence prediction.
It produces contextualized embeddings useful for downstream tasks like
classification, NER, and question answering.
""", "text/plain"),
    ("sample_vectors.txt", b"""Vector Databases and Semantic Search

Vector databases store high-dimensional embedding vectors. Approximate
nearest neighbor (ANN) search finds similar vectors efficiently. HNSW
(Hierarchical Navigable Small World) graphs enable fast ANN search.

Qdrant is an open-source vector database written in Rust. It supports
filtering, payload storage, and multiple distance metrics (cosine, dot
product, Euclidean). Collections are partitioned for scalability.

Hybrid search combines dense vector search with sparse keyword search.
BM25 and TF-IDF are common sparse retrieval methods. Reciprocal rank
fusion (RRF) merges results from multiple retrieval methods.

RAG (Retrieval Augmented Generation) retrieves relevant chunks then feeds
them to an LLM as context. This grounds model responses in facts and
reduces hallucination. Chunk size and overlap affect retrieval quality.
""", "text/plain"),
]

SEARCH_QUERIES = [
    "machine learning algorithms",
    "neural network training",
    "vector embedding similarity",
    "natural language processing",
    "transformer attention mechanism",
    "semantic search retrieval",
    "gradient descent optimization",
    "clustering unsupervised learning",
    "BERT tokenization",
    "RAG retrieval augmented generation",
    "dimensionality reduction PCA",
    "approximate nearest neighbor search",
]

# ── Async workers ──────────────────────────────────────────────────────────────
async def do_search(client: httpx.AsyncClient, headers: dict, results: Results, query: str) -> None:
    t0 = time.monotonic()
    try:
        r = await client.get(
            "/search",
            params={"q": query, "mode": "hybrid", "top_k": 5},
            headers=headers,
            timeout=30,
        )
        ms = (time.monotonic() - t0) * 1000
        err = None if r.status_code < 400 else f"HTTP {r.status_code}: {r.text[:100]}"
        results.add(ms, r.status_code, err)
    except Exception as e:
        ms = (time.monotonic() - t0) * 1000
        results.add(ms, 0, str(e)[:120])


async def do_health(client: httpx.AsyncClient, results: Results) -> None:
    t0 = time.monotonic()
    try:
        r = await client.get("/health", timeout=10)
        ms = (time.monotonic() - t0) * 1000
        results.add(ms, r.status_code)
    except Exception as e:
        ms = (time.monotonic() - t0) * 1000
        results.add(ms, 0, str(e)[:80])


async def do_upload(client: httpx.AsyncClient, headers: dict, results: Results) -> Optional[str]:
    doc_name, doc_bytes, mime = SAMPLE_DOCS[int(time.monotonic() * 1000) % len(SAMPLE_DOCS)]
    # Append a UUID so every upload has a unique checksum — avoids 409 dedup rejection
    unique_id = uuid.uuid4().hex
    unique_bytes = doc_bytes + f"\n\n[load-test-id: {unique_id}]\n".encode()
    unique_name = f"load_{unique_id[:8]}_{doc_name}"
    t0 = time.monotonic()
    try:
        r = await client.post(
            "/ingest/upload",
            files={"file": (unique_name, unique_bytes, mime)},
            headers=headers,
            timeout=30,
        )
        ms = (time.monotonic() - t0) * 1000
        # 409 = duplicate (shouldn't happen with unique content, but not a server crash)
        if r.status_code in (200, 202):
            results.add(ms, r.status_code)
            return r.json().get("document_id")
        else:
            results.add(ms, r.status_code, f"HTTP {r.status_code}: {r.text[:100]}")
    except Exception as e:
        ms = (time.monotonic() - t0) * 1000
        results.add(ms, 0, str(e)[:120])
    return None


async def do_list_docs(client: httpx.AsyncClient, headers: dict, results: Results) -> None:
    t0 = time.monotonic()
    try:
        r = await client.get("/documents", headers=headers, timeout=15)
        ms = (time.monotonic() - t0) * 1000
        err = None if r.status_code < 400 else f"HTTP {r.status_code}: {r.text[:100]}"
        results.add(ms, r.status_code, err)
    except Exception as e:
        ms = (time.monotonic() - t0) * 1000
        results.add(ms, 0, str(e)[:120])


# ── Test scenarios ─────────────────────────────────────────────────────────────
async def run_concurrent_searches(base_url: str, api_key: str, concurrency: int, total: int) -> Results:
    """Fire `total` search requests with `concurrency` parallel."""
    headers = {"X-Api-Key": api_key}
    results = Results(f"search c={concurrency}")
    sem = asyncio.Semaphore(concurrency)

    async def bounded_search(i: int) -> None:
        async with sem:
            q = SEARCH_QUERIES[i % len(SEARCH_QUERIES)]
            await do_search(client, headers, results, q)

    async with httpx.AsyncClient(base_url=base_url) as client:
        await asyncio.gather(*[bounded_search(i) for i in range(total)])

    return results


async def run_mixed_load(base_url: str, api_key: str, concurrency: int, duration_s: int) -> dict[str, Results]:
    """Mixed load: searches + health checks + list docs for `duration_s` seconds."""
    headers = {"X-Api-Key": api_key}
    r_search = Results("search")
    r_health = Results("health")
    r_list   = Results("list_docs")

    stop = asyncio.Event()

    async def search_loop() -> None:
        i = 0
        while not stop.is_set():
            await do_search(client, headers, r_search, SEARCH_QUERIES[i % len(SEARCH_QUERIES)])
            i += 1

    async def health_loop() -> None:
        while not stop.is_set():
            await do_health(client, r_health)
            await asyncio.sleep(1)

    async def list_loop() -> None:
        while not stop.is_set():
            await do_list_docs(client, headers, r_list)
            await asyncio.sleep(2)

    async with httpx.AsyncClient(base_url=base_url) as client:
        tasks = (
            [asyncio.create_task(search_loop()) for _ in range(concurrency)] +
            [asyncio.create_task(health_loop())] +
            [asyncio.create_task(list_loop())]
        )
        await asyncio.sleep(duration_s)
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)

    return {"search": r_search, "health": r_health, "list_docs": r_list}


async def run_upload_flood(base_url: str, api_key: str, concurrency: int, total: int, cleanup: bool = True) -> Results:
    """Upload `total` documents with `concurrency` parallel. Cleans up afterwards."""
    headers = {"X-Api-Key": api_key}
    results = Results(f"upload c={concurrency}")
    sem = asyncio.Semaphore(concurrency)
    doc_ids: list[str] = []
    lock = asyncio.Lock()

    async def bounded_upload() -> None:
        async with sem:
            doc_id = await do_upload(client, headers, results)
            if doc_id:
                async with lock:
                    doc_ids.append(doc_id)

    async with httpx.AsyncClient(base_url=base_url) as client:
        await asyncio.gather(*[bounded_upload() for _ in range(total)])

        if cleanup and doc_ids:
            print(f"    cleaning up {len(doc_ids)} test docs …", end="", flush=True)
            delete_tasks = [
                client.delete(f"/documents/{did}", headers=headers, timeout=10)
                for did in doc_ids
            ]
            await asyncio.gather(*delete_tasks, return_exceptions=True)
            print(f"\r    cleaned up {len(doc_ids)} test docs      ")

    return results


async def run_ramp_test(base_url: str, api_key: str) -> None:
    """Ramp concurrency 1→5→10→20→50→100 — find where error rate spikes."""
    print(f"\n{c(BOLD, '═══ RAMP TEST (search) ═══')}")
    print(f"  Increasing concurrency until error rate > 10% or p99 > 10s\n")

    levels   = [1, 5, 10, 20, 50, 100]
    previous_error_rate = 0.0

    for level in levels:
        r = await run_concurrent_searches(base_url, api_key, concurrency=level, total=level * 3)
        n   = len(r.latencies)
        err = sum(1 for s in r.status_codes if s >= 400 or s == 0)
        rate = err / n * 100 if n else 100
        p99  = sorted(r.latencies)[int(0.99 * n)] if n else 0

        r.report()

        if rate > 10:
            print(f"\n  {c(RED, '⚠ BREAKING POINT')} at concurrency={level}  error_rate={rate:.1f}%")
            break
        if p99 > 10_000:
            print(f"\n  {c(YELLOW, '⚠ LATENCY SPIKE')} at concurrency={level}  p99={p99:.0f}ms")
            break
        if rate > previous_error_rate + 5:
            print(f"  {c(YELLOW, '△ Error rate jumped')} +{rate - previous_error_rate:.1f}% at concurrency={level}")

        previous_error_rate = rate
        await asyncio.sleep(2)  # brief cool-down between levels
    else:
        print(f"\n  {c(GREEN, '✓ Server stable up to concurrency=100')}")


# ── Checklist pre-run ──────────────────────────────────────────────────────────
async def check_health(base_url: str, api_key: str) -> bool:
    print(f"\n{c(BOLD, '═══ PRE-FLIGHT ═══')}")
    async with httpx.AsyncClient(base_url=base_url) as client:
        try:
            r = await client.get("/health", timeout=10)
            if r.status_code == 200:
                print(f"  {c(GREEN, '✓')} Health OK  {r.json()}")
            else:
                print(f"  {c(RED, '✗')} Health returned HTTP {r.status_code}")
                return False
        except Exception as e:
            print(f"  {c(RED, '✗')} Cannot reach {base_url}: {e}")
            return False

        try:
            r = await client.get("/documents", headers={"X-Api-Key": api_key}, timeout=10)
            if r.status_code == 200:
                n = len(r.json())
                print(f"  {c(GREEN, '✓')} Auth OK  ({n} documents in tenant)")
            elif r.status_code == 401:
                print(f"  {c(RED, '✗')} Auth FAILED — check --api-key")
                return False
            else:
                print(f"  {c(YELLOW, '△')} Documents returned HTTP {r.status_code}")
        except Exception as e:
            print(f"  {c(RED, '✗')} Auth check failed: {e}")
            return False

    return True


# ── Main ───────────────────────────────────────────────────────────────────────
async def main() -> None:
    ap = argparse.ArgumentParser(description="Cortex KB load test")
    ap.add_argument("--base-url", default="https://knowledge.basivo.in", help="KB base URL")
    ap.add_argument("--api-key",  required=True, help="X-Api-Key value")
    ap.add_argument("--with-uploads", action="store_true", help="Include upload load test")
    ap.add_argument("--ramp",    action="store_true", help="Ramp concurrency to find breaking point")
    ap.add_argument("--spike",   type=int, default=0, metavar="N", help="Sustain N concurrent searches for --duration seconds")
    ap.add_argument("--duration",type=int, default=30, help="Duration (s) for --spike test (default 30)")
    args = ap.parse_args()

    base = args.base_url.rstrip("/")
    key  = args.api_key

    ok = await check_health(base, key)
    if not ok:
        sys.exit(1)

    # ── Ramp test ──────────────────────────────────────────────────────────────
    if args.ramp:
        await run_ramp_test(base, key)
        return

    # ── Spike / sustained test ─────────────────────────────────────────────────
    if args.spike:
        print(f"\n{c(BOLD, f'═══ SPIKE TEST: {args.spike} concurrent users × {args.duration}s ═══')}")
        results = await run_mixed_load(base, key, concurrency=args.spike, duration_s=args.duration)
        for r in results.values():
            r.report()
        return

    # ── Standard load test ─────────────────────────────────────────────────────
    print(f"\n{c(BOLD, '═══ SEARCH LOAD TEST ═══')}")
    all_results: list[Results] = []

    for conc, total in [(1, 10), (5, 50), (10, 100), (20, 100), (50, 150)]:
        print(f"  Running {total} searches @ concurrency={conc} …", end="", flush=True)
        t0 = time.monotonic()
        r = await run_concurrent_searches(base, key, conc, total)
        elapsed = time.monotonic() - t0
        print(f"\r", end="")
        r.label = f"search c={conc:>3} n={total:>3}"
        r.report()
        all_results.append(r)
        if sum(1 for s in r.status_codes if s >= 400 or s == 0) / len(r.status_codes) > 0.20:
            print(f"\n  {c(RED, '⚠ >20% errors — stopping search ramp early')}")
            break
        await asyncio.sleep(1)

    # ── Mixed load ─────────────────────────────────────────────────────────────
    print(f"\n{c(BOLD, '═══ MIXED LOAD (search + health + list) 30s ═══')}")
    print(f"  10 concurrent search workers + 1 health poller + 1 list poller …")
    mixed = await run_mixed_load(base, key, concurrency=10, duration_s=30)
    for r in mixed.values():
        r.report()

    # ── Upload flood (optional) ────────────────────────────────────────────────
    if args.with_uploads:
        print(f"\n{c(BOLD, '═══ UPLOAD FLOOD ═══')}")
        for conc, total in [(1, 3), (3, 9), (5, 15)]:
            print(f"  Uploading {total} docs @ concurrency={conc} …", end="", flush=True)
            r = await run_upload_flood(base, key, conc, total)
            print(f"\r", end="")
            r.label = f"upload c={conc:>2} n={total:>2}"
            r.report()
            if sum(1 for s in r.status_codes if s >= 400 or s == 0) / len(r.status_codes) > 0.20:
                print(f"\n  {c(RED, '⚠ >20% upload errors — stopping')}")
                break
            await asyncio.sleep(2)

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{c(BOLD, '═══ SUMMARY ═══')}")
    total_errors = sum(
        sum(1 for s in r.status_codes if s >= 400 or s == 0)
        for r in all_results
    )
    total_reqs = sum(len(r.latencies) for r in all_results)
    overall_rate = total_errors / total_reqs * 100 if total_reqs else 0

    if overall_rate == 0:
        print(f"  {c(GREEN, '✓ Zero errors across all search tests')}")
    elif overall_rate < 5:
        print(f"  {c(YELLOW, f'△ {overall_rate:.1f}% error rate — acceptable but investigate')}")
    else:
        print(f"  {c(RED, f'✗ {overall_rate:.1f}% error rate — server unstable under load')}")

    print(f"  Total requests: {total_reqs}  errors: {total_errors}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
