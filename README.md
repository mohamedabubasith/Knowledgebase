# Atlas KB — Local Production Knowledge Base

Atlas KB is a private, multilingual retrieval-augmented generation platform. Documents are parsed by Unstructured, embedded with `nomic-embed-text`, stored in an external PostgreSQL/pgvector database, and answered by `llama3.2:3b`. All AI inference stays inside Ollama.

## Architecture

- **API:** FastAPI, async SQLAlchemy/asyncpg, JWT RBAC, pgvector
- **Pipeline:** Redis + ARQ worker, Unstructured, persistent upload volume
- **AI:** Ollama embedding and generation models; no external AI APIs
- **Admin:** Next.js 14 dashboard with users, KBs, documents, queue health, and prompt audit logs
- **Edge:** Nginx routes `/api` to FastAPI and all other traffic to Next.js

PostgreSQL is intentionally **not** included in Compose. Supply an external PostgreSQL server whose database user can execute `CREATE EXTENSION vector`.

## Quick start

```bash
cp .env.example .env
# Edit DATABASE_URL, SECRET_KEY, and super-admin credentials
docker compose up --build
```

Open `http://localhost`, sign in with the configured super-admin account, and create a knowledge base. API docs are available at `http://localhost/docs`.

On first startup, Compose waits for Ollama and pulls both required models. FastAPI enables pgvector, creates tables, creates the upload directory, and idempotently seeds the super administrator.

## Operations

```bash
docker compose logs -f api worker
docker compose ps
docker compose down                 # retained volumes
docker compose down -v              # deletes uploads, Redis data, and Ollama models
```

Uploads are always queued; the API never parses documents synchronously. Query successes and failures are written to `prompt_logs`. Keep `.env` private and use a randomly generated 32+ character `SECRET_KEY` in production.

## API overview

All application endpoints live under `/api/v1`. Authenticate through `/api/v1/auth/login`, then send `Authorization: Bearer <access_token>`. Important groups include `/users`, `/knowledge-bases`, nested document routes, `/query`, and `/admin`.

## Development checks

```bash
python -m compileall app
cd frontend && npm install && npm run build

docker compose config
```
