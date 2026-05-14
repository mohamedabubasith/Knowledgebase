"""
Cortex KB — entry point.
Startup order is strict and frozen. See inline comments.
"""
import asyncio
import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.startup import run_startup_probes
from app.db.pool import close_pool, init_pool
from app.parsers.router import init_parser_pool
from app.storage.minio_client import init_minio
from app.vectorstore import init_vector_store
from app.workers.queue import register_task, shutdown_workers

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("cortex_kb_starting")

    # 1. Postgres — init engine then auto-create all tables
    init_pool()
    from app.db.migrate import run_migrations
    await run_migrations()

    # 2. MinIO (non-negotiable)
    init_minio()

    # 3. Probe services → freeze registry (all backend decisions made here)
    await run_startup_probes()

    # 4. Vector store (depends on frozen registry)
    init_vector_store()

    # 5. Load ST model into memory if selected
    from app.core.registry import registry
    if registry.embed_backend == "sentence_transformers":
        from app.embedding.embedder import load_sentence_transformers
        await asyncio.get_event_loop().run_in_executor(None, load_sentence_transformers)

    # 6. Parser CPU process pool
    init_parser_pool(max_workers=settings.parse_process_workers)

    # 7. Launch pipeline workers (N concurrent per stage)
    from app.workers.ingest_worker import run_ingest_worker
    from app.workers.embed_worker import run_embed_worker
    from app.workers.index_worker import run_index_worker
    from app.workers.purge_worker import run_purge_worker

    for _ in range(settings.worker_concurrency):
        register_task(asyncio.create_task(run_ingest_worker()))
        register_task(asyncio.create_task(run_embed_worker()))
        register_task(asyncio.create_task(run_index_worker()))
        register_task(asyncio.create_task(run_purge_worker()))

    log.info("cortex_kb_ready", **registry.as_dict())
    yield

    log.info("cortex_kb_shutting_down")
    await shutdown_workers()
    await close_pool()
    log.info("cortex_kb_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Cortex KB",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.api.routes import admin, bootstrap, documents, health, ingest, search, status

    app.include_router(bootstrap.router)
    app.include_router(ingest.router)
    app.include_router(search.router)
    app.include_router(documents.router)
    app.include_router(status.router)
    app.include_router(health.router)
    app.include_router(admin.router)

    return app


app = create_app()
