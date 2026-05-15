"""
Worker task registry — tracks asyncio tasks for clean shutdown.
Job dispatching is now handled by the PostgreSQL-backed db_queue module.
"""
import asyncio

_worker_tasks: list[asyncio.Task] = []


def register_task(task: asyncio.Task) -> None:
    _worker_tasks.append(task)


async def shutdown_workers() -> None:
    for task in _worker_tasks:
        task.cancel()
    await asyncio.gather(*_worker_tasks, return_exceptions=True)
