"""
Asyncio queues for ingestion pipeline stages.
All queues initialized at startup, workers launched as background tasks.
"""
import asyncio
from app.core.config import settings

ingest_queue: asyncio.Queue = asyncio.Queue(maxsize=settings.ingest_queue_size)
embed_queue: asyncio.Queue = asyncio.Queue(maxsize=settings.ingest_queue_size)
index_queue: asyncio.Queue = asyncio.Queue(maxsize=settings.ingest_queue_size)
purge_queue: asyncio.Queue = asyncio.Queue(maxsize=settings.ingest_queue_size)

_worker_tasks: list[asyncio.Task] = []


def register_task(task: asyncio.Task) -> None:
    _worker_tasks.append(task)


async def shutdown_workers() -> None:
    for task in _worker_tasks:
        task.cancel()
    await asyncio.gather(*_worker_tasks, return_exceptions=True)
