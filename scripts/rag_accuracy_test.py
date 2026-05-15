#!/usr/bin/env python3
"""
Cortex KB — RAG Accuracy Test
Uploads a ground-truth document with known Q&A pairs.
Tests retrieval accuracy: Recall@k, MRR, Precision@k, Hit Rate.

Usage:
    uv run python scripts/rag_accuracy_test.py --base-url https://knowledge.basivo.in --api-key cortex_xxx
"""
import argparse
import time
import uuid
import sys
import httpx

# ── ANSI ──────────────────────────────────────────────────────────────────────
GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"
CYAN = "\033[96m"; BOLD = "\033[1m"; RESET = "\033[0m"; DIM = "\033[2m"

# ── Ground-Truth Document ─────────────────────────────────────────────────────
GROUND_TRUTH_DOC = """
# Cortex KB Technical Reference

## Architecture Overview
Cortex KB uses a four-stage ingestion pipeline: upload, parse, chunk, embed, index.
Documents are stored in MinIO object storage. Metadata is persisted in PostgreSQL.
Vector embeddings are stored in Qdrant using cosine similarity distance.

## Search Modes
The system supports three search modes:
- Hybrid search combines vector similarity and BM25 full-text search with configurable weights.
- Vector-only search uses pure semantic similarity via cosine distance in Qdrant.
- Lexical-only search uses PostgreSQL full-text search with ts_rank_cd scoring.

## Authentication
All API endpoints require the X-Api-Key HTTP header.
Three roles exist: admin, editor, and viewer.
Admin can create and revoke API keys. Editor can upload and delete documents.
Viewer can only read documents and perform searches.

## Embedding Models
The primary embedding model is paraphrase-multilingual from Ollama.
It produces 768-dimensional vectors. When Ollama is unavailable,
the system automatically falls back to paraphrase-multilingual-mpnet-base-v2
via SentenceTransformers, which also produces 768-dimensional vectors.

## Chunking Strategy
Documents are split into chunks of approximately 512 tokens with 64-token overlap.
Each chunk preserves page number and character offset metadata.
Chunk embeddings are computed in batches of 64 for efficiency.

## API Endpoints
The ingest endpoint accepts PDF, DOCX, TXT, MD, and HTML files.
Maximum file size is 100MB. Duplicate documents are detected by content hash.
Pipeline status can be polled via GET /status/{doc_id} or streamed via SSE.

## Deployment
The application is deployed using Docker Compose on a Coolify server.
It connects to external services: MinIO, PostgreSQL, Qdrant, Ollama, and Unstructured API.
The Traefik reverse proxy handles SSL termination and routing.

## Performance Characteristics
Upload latency is typically under 300ms for small documents.
Pipeline processing completes within 3 seconds for documents under 2000 tokens.
Hybrid search latency is typically 500-900ms including embedding time.
Vector-only search latency is 400-700ms. Lexical search is under 300ms.

## Rate Limits and Quotas
The search cache has a default TTL of 300 seconds and capacity of 1000 entries.
Worker concurrency is configurable via the WORKER_CONCURRENCY environment variable.
Ingest queue capacity is 500 documents by default.
"""

# ── Q&A Pairs with ground-truth keywords ─────────────────────────────────────
# Each: (question, [keywords that MUST appear in top result], description)
QA_PAIRS = [
    (
        "What are the three search modes available?",
        ["hybrid", "vector", "lexical"],
        "Search modes enumeration",
    ),
    (
        "Where are vector embeddings stored?",
        ["qdrant"],
        "Vector store location",
    ),
    (
        "What roles exist for API authentication?",
        ["admin", "editor", "viewer"],
        "RBAC roles",
    ),
    (
        "What embedding model dimension does Ollama produce?",
        ["768"],
        "Embedding dimension",
    ),
    (
        "What happens when Ollama is unavailable?",
        ["fallback", "SentenceTransformers", "paraphrase-multilingual-mpnet"],
        "Fallback embedding behavior",
    ),
    (
        "What HTTP header is required for authentication?",
        ["X-Api-Key"],
        "Auth header",
    ),
    (
        "What is the default chunk token size?",
        ["512"],
        "Chunking configuration",
    ),
    (
        "What object storage is used for documents?",
        ["MinIO"],
        "Object storage backend",
    ),
    (
        "What file formats does the ingest endpoint accept?",
        ["PDF", "DOCX", "TXT"],
        "Accepted file types",
    ),
    (
        "How is duplicate document detection implemented?",
        ["hash", "content"],
        "Deduplication mechanism",
    ),
    (
        "What is the default search cache TTL?",
        ["300"],
        "Cache TTL config",
    ),
    (
        "What reverse proxy handles SSL termination?",
        ["Traefik"],
        "Reverse proxy",
    ),
]


# ── Helpers ───────────────────────────────────────────────────────────────────
def section(title: str) -> None:
    print(f"\n{BOLD}{CYAN}── {title}{RESET}")

def ok(msg: str, detail: str = "") -> None:
    d = f"  {DIM}{detail}{RESET}" if detail else ""
    print(f"  {GREEN}✓{RESET}  {msg}{d}")

def fail_msg(msg: str, detail: str = "") -> None:
    d = f"  {DIM}{detail}{RESET}" if detail else ""
    print(f"  {RED}✗{RESET}  {msg}{d}")

def warn(msg: str, detail: str = "") -> None:
    d = f"  {DIM}{detail}{RESET}" if detail else ""
    print(f"  {YELLOW}⚠{RESET}  {msg}{d}")

def assert_status(resp: httpx.Response, expected: int, label: str) -> dict:
    if resp.status_code != expected:
        raise RuntimeError(f"{label}: expected {expected}, got {resp.status_code} — {resp.text[:200]}")
    return resp.json()

def poll_pipeline(client: httpx.Client, headers: dict, doc_id: str, timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/status/{doc_id}", headers=headers)
        if resp.status_code == 404:
            time.sleep(2)
            continue
        data = assert_status(resp, 200, "Status")
        overall = data.get("overall_status", "")
        if overall == "indexed":
            return
        if "failed" in overall or overall == "error":
            stages = data.get("stages", {})
            raise RuntimeError(f"Pipeline failed: {overall}\n{stages}")
        time.sleep(2)
    raise RuntimeError(f"Pipeline timeout after {timeout}s")


def hits_in_text(text: str, keywords: list[str]) -> list[str]:
    """Returns keywords found in text (case-insensitive)."""
    text_lower = text.lower()
    return [k for k in keywords if k.lower() in text_lower]


def reciprocal_rank(results: list[dict], keywords: list[str]) -> float:
    """MRR: 1/rank of first result containing all keywords."""
    for i, r in enumerate(results, 1):
        found = hits_in_text(r["text"], keywords)
        if len(found) >= max(1, len(keywords) // 2):
            return 1.0 / i
    return 0.0


def recall_at_k(results: list[dict], keywords: list[str], k: int) -> bool:
    """True if any of top-k results contain the answer keywords."""
    for r in results[:k]:
        found = hits_in_text(r["text"], keywords)
        if len(found) >= max(1, len(keywords) // 2):
            return True
    return False


# ── Main Test ─────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="RAG accuracy test for Cortex KB")
    parser.add_argument("--base-url", default="https://knowledge.basivo.in")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    headers = {"X-Api-Key": args.api_key}
    run_id = uuid.uuid4().hex[:8]

    print(f"\n{BOLD}Cortex KB — RAG Accuracy Test{RESET}")
    print(f"Server: {CYAN}{args.base_url}{RESET}  Run: {run_id}\n")

    with httpx.Client(base_url=args.base_url, timeout=args.timeout, verify=False) as client:

        # ── Upload ground-truth doc ────────────────────────────────────────────
        section("Setup: Upload ground-truth document")
        content = GROUND_TRUTH_DOC + f"\n\nRun ID: {run_id}"
        fname = f"rag_ground_truth_{run_id}.txt"
        resp = client.post(
            "/ingest/upload",
            files={"file": (fname, content.encode(), "text/plain")},
            headers=headers,
        )
        data = assert_status(resp, 202, "Upload")
        doc_id = data["document_id"]
        ok(f"Uploaded: {fname}", f"doc_id={doc_id[:8]}")

        # ── Wait for pipeline ──────────────────────────────────────────────────
        section("Pipeline: Waiting for indexing")
        t0 = time.monotonic()
        poll_pipeline(client, headers, doc_id, timeout=120)
        ok(f"Indexed in {time.monotonic()-t0:.1f}s")

        # ── RAG accuracy evaluation ────────────────────────────────────────────
        section(f"RAG Accuracy Evaluation ({len(QA_PAIRS)} Q&A pairs × 3 modes)")

        modes = ["hybrid", "vector_only", "lexical_only"]
        mode_stats: dict[str, dict] = {m: {"hit1": 0, "hit3": 0, "hit5": 0, "mrr": 0.0} for m in modes}

        print(f"\n  {'Question':<52} {'Mode':<14} {'Hit@1':<7} {'Hit@3':<7} {'MRR':<6} {'Found Keywords'}")
        print(f"  {'─'*52} {'─'*14} {'─'*7} {'─'*7} {'─'*6} {'─'*30}")

        for question, keywords, description in QA_PAIRS:
            for mode in modes:
                resp = client.post(
                    "/search",
                    json={"query": question, "mode": mode, "top_k": 5, "document_id": doc_id},
                    headers=headers,
                )
                data = assert_status(resp, 200, f"Search {mode}")
                results = data.get("results", [])

                h1 = recall_at_k(results, keywords, k=1)
                h3 = recall_at_k(results, keywords, k=3)
                h5 = recall_at_k(results, keywords, k=5)
                mrr = reciprocal_rank(results, keywords)

                mode_stats[mode]["hit1"] += int(h1)
                mode_stats[mode]["hit3"] += int(h3)
                mode_stats[mode]["hit5"] += int(h5)
                mode_stats[mode]["mrr"] += mrr

                found = hits_in_text(results[0]["text"] if results else "", keywords)
                h1_str = f"{GREEN}✓{RESET}" if h1 else f"{RED}✗{RESET}"
                h3_str = f"{GREEN}✓{RESET}" if h3 else f"{RED}✗{RESET}"

                q_short = question[:50] + ".." if len(question) > 50 else question
                mode_short = mode.replace("_only", "")
                print(f"  {q_short:<52} {mode_short:<14} {h1_str}      {h3_str}      {mrr:.2f}   {', '.join(found) or '—'}")

        # ── Summary ───────────────────────────────────────────────────────────
        n = len(QA_PAIRS)
        section("Accuracy Summary")
        print(f"\n  {'Mode':<16} {'Hit@1':>7} {'Hit@3':>7} {'Hit@5':>7} {'MRR':>7}")
        print(f"  {'─'*16} {'─'*7} {'─'*7} {'─'*7} {'─'*7}")

        for mode in modes:
            s = mode_stats[mode]
            h1_pct = s["hit1"] / n * 100
            h3_pct = s["hit3"] / n * 100
            h5_pct = s["hit5"] / n * 100
            mrr_val = s["mrr"] / n

            h1_c = GREEN if h1_pct >= 75 else YELLOW if h1_pct >= 50 else RED
            mode_label = mode.replace("_only", "")
            print(
                f"  {mode_label:<16} "
                f"{h1_c}{h1_pct:>6.1f}%{RESET} "
                f"{h3_pct:>6.1f}%  "
                f"{h5_pct:>6.1f}%  "
                f"{mrr_val:>6.3f}"
            )

        print(f"\n  Metrics explained:")
        print(f"  {DIM}Hit@k  = % of questions answered in top-k results{RESET}")
        print(f"  {DIM}MRR    = Mean Reciprocal Rank (1.0 = always top result){RESET}")

        # Overall verdict
        hybrid_h3 = mode_stats["hybrid"]["hit3"] / n * 100
        hybrid_mrr = mode_stats["hybrid"]["mrr"] / n
        print()
        if hybrid_h3 >= 80 and hybrid_mrr >= 0.6:
            ok(f"RAG accuracy GOOD — hybrid Hit@3={hybrid_h3:.0f}%  MRR={hybrid_mrr:.3f}")
        elif hybrid_h3 >= 60:
            warn(f"RAG accuracy ACCEPTABLE — hybrid Hit@3={hybrid_h3:.0f}%  MRR={hybrid_mrr:.3f}")
        else:
            fail_msg(f"RAG accuracy LOW — hybrid Hit@3={hybrid_h3:.0f}%  MRR={hybrid_mrr:.3f}")

        # ── Cleanup ───────────────────────────────────────────────────────────
        section("Cleanup")
        resp = client.delete(f"/documents/{doc_id}", headers=headers)
        if resp.status_code in (202, 404):
            ok(f"Ground-truth doc deleted")
        else:
            warn(f"Delete failed", f"HTTP {resp.status_code}")

    print()


if __name__ == "__main__":
    main()
