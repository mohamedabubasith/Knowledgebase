# Cortex KB

Production-grade self-hosted knowledge base with hybrid search.

## Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI + SQLAlchemy 2.0 async |
| Database | PostgreSQL (auto-migrated on startup) |
| Object Storage | MinIO |
| Vector Store | Qdrant (ChromaDB fallback) |
| Embeddings | Ollama (SentenceTransformers fallback) |
| Parsing | Unstructured API → local parsers (PyMuPDF, python-docx, BS4) |
| Search | Hybrid (vector + FTS), vector-only, lexical-only |

## Quick Start

```bash
# 1. Copy env
cp .env.coolify .env   # edit values

# 2. Run
docker compose up -d

# 3. Bootstrap (first run only — creates admin key)
curl -X POST http://localhost:8080/bootstrap

# 4. Save the returned api_key — shown once
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/bootstrap` | POST | First-run setup — creates admin key |
| `/health` | GET | System health + active backends |
| `/ingest/upload` | POST | Upload document (PDF, DOCX, TXT, MD, HTML) |
| `/status/{doc_id}` | GET | Pipeline status for a document |
| `/status/{doc_id}/stream` | GET | SSE stream of pipeline events |
| `/search` | POST | Hybrid / vector / lexical search |
| `/documents` | GET | List documents |
| `/documents/{doc_id}` | GET | Document detail |
| `/documents/{doc_id}/chunks` | GET | Document chunks |
| `/documents/{doc_id}` | DELETE | Delete document |
| `/admin/api-keys` | POST | Create API key |
| `/admin/api-keys` | GET | List API keys |
| `/admin/api-keys/{id}` | DELETE | Revoke API key |

Full interactive docs at `/docs`.

## Auth

All endpoints require `X-Api-Key` header. Roles: `admin`, `editor`, `viewer`.

```bash
curl -H "X-Api-Key: cortex_xxx" http://localhost:8080/documents
```

## Pipeline

Upload triggers a 5-stage async pipeline:

```
upload → parse → chunk → embed → index
```

Poll status via `GET /status/{doc_id}` or stream events via SSE.

## Search

```bash
curl -X POST http://localhost:8080/search \
  -H "X-Api-Key: cortex_xxx" \
  -H "Content-Type: application/json" \
  -d '{"query": "your question", "mode": "hybrid", "top_k": 10}'
```

Modes: `hybrid` (default), `vector_only`, `lexical_only`.

## Deploy (Coolify)

1. Push repo to GitHub
2. Coolify → New Resource → Docker Compose
3. Add env vars from `.env.coolify`
4. Deploy

## Development

```bash
# Install deps
uv sync

# Run locally
uv run uvicorn app.main:app --reload --port 8080

# E2E test (server must be running)
uv run python scripts/e2e_test.py

# Unit tests
uv run pytest tests/ -v
```
