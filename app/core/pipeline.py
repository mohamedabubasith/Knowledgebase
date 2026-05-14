"""
PipelineTracker — writes stage updates to Postgres + broadcasts to SSE subscribers.
Workers call update_stage(). SSE handlers subscribe via subscribe()/unsubscribe().

Event bus is in-process: tenant_id → list of asyncio.Queue.
No Redis required.
"""
import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import func

from app.db.models import Document, PipelineStage
from app.db.session import get_session_factory

log = structlog.get_logger(__name__)

STAGES = ("upload", "parse", "chunk", "embed", "index")
STAGE_WEIGHT = {"upload": 10, "parse": 20, "chunk": 15, "embed": 40, "index": 15}
_STAGE_ORDER = {s: i for i, s in enumerate(STAGES)}


# ── In-process SSE event bus ──────────────────────────────────────────────────
_subscribers: dict[str, list[asyncio.Queue]] = {}
_bus_lock = asyncio.Lock()


async def subscribe(tenant_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    async with _bus_lock:
        _subscribers.setdefault(tenant_id, []).append(q)
    return q


async def unsubscribe(tenant_id: str, q: asyncio.Queue) -> None:
    async with _bus_lock:
        subs = _subscribers.get(tenant_id, [])
        try:
            subs.remove(q)
        except ValueError:
            pass


async def _broadcast(tenant_id: str, event: dict) -> None:
    async with _bus_lock:
        subs = list(_subscribers.get(tenant_id, []))
    for q in subs:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


# ── PipelineTracker ───────────────────────────────────────────────────────────

async def update_stage(
    document_id: str,
    tenant_id: str,
    stage: str,
    status: str,
    detail: Optional[dict] = None,
) -> None:
    """
    Upsert stage row in Postgres. Broadcast SSE event.
    status: pending | processing | done | failed | skipped
    """
    now = datetime.now(timezone.utc)
    started_at = now if status == "processing" else None
    completed_at = now if status in ("done", "failed", "skipped") else None

    factory = get_session_factory()
    async with factory() as session:
        stmt = pg_insert(PipelineStage).values(
            document_id=document_id,
            tenant_id=tenant_id,
            stage=stage,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            detail=detail,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["document_id", "stage"],
            set_={
                "status": stmt.excluded.status,
                "started_at": func.coalesce(PipelineStage.started_at, stmt.excluded.started_at),
                "completed_at": stmt.excluded.completed_at,
                "detail": stmt.excluded.detail,
            },
        )
        await session.execute(stmt)
        await session.commit()

    event = {
        "document_id": document_id,
        "stage": stage,
        "status": status,
        "detail": detail or {},
        "ts": now.isoformat(),
    }
    await _broadcast(tenant_id, event)
    log.info("pipeline_stage", document_id=document_id, stage=stage, status=status)


def _stage_row_to_dict(row: PipelineStage) -> dict:
    return {
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "detail": row.detail or {},
    }


def _empty_stages() -> dict:
    return {s: {"status": "pending", "started_at": None, "completed_at": None, "detail": {}} for s in STAGES}


async def get_pipeline_status(document_id: str, tenant_id: str) -> Optional[dict]:
    factory = get_session_factory()
    async with factory() as session:
        doc = (await session.execute(
            select(Document)
            .options(selectinload(Document.pipeline_stages))
            .where(Document.id == document_id, Document.tenant_id == tenant_id)
        )).scalar_one_or_none()

    if not doc:
        return None

    stages = _empty_stages()
    for row in sorted(doc.pipeline_stages, key=lambda r: _STAGE_ORDER.get(r.stage, 99)):
        stages[row.stage] = _stage_row_to_dict(row)

    return {
        "document_id": doc.id,
        "filename": doc.filename,
        "mime_type": doc.mime_type,
        "overall_status": doc.status,
        "progress_pct": _compute_progress(stages),
        "file_size": doc.file_size,
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
        "stages": stages,
    }


async def list_pipeline_statuses(
    tenant_id: str,
    limit: int = 20,
    offset: int = 0,
    status_filter: Optional[str] = None,
) -> list[dict]:
    factory = get_session_factory()
    async with factory() as session:
        q = (
            select(Document)
            .options(selectinload(Document.pipeline_stages))
            .where(Document.tenant_id == tenant_id, Document.status != "deleted")
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status_filter:
            q = q.where(Document.status == status_filter)
        docs = (await session.execute(q)).scalars().all()

    result = []
    for doc in docs:
        stages = _empty_stages()
        for row in sorted(doc.pipeline_stages, key=lambda r: _STAGE_ORDER.get(r.stage, 99)):
            stages[row.stage] = _stage_row_to_dict(row)
        result.append({
            "document_id": doc.id,
            "filename": doc.filename,
            "overall_status": doc.status,
            "progress_pct": _compute_progress(stages),
            "file_size": doc.file_size,
            "created_at": doc.created_at.isoformat(),
            "updated_at": doc.updated_at.isoformat(),
            "stages": stages,
        })

    return result


def _compute_progress(stages: dict) -> int:
    done_weight = sum(
        STAGE_WEIGHT[s] for s, v in stages.items() if v["status"] in ("done", "skipped")
    )
    proc_weight = sum(
        STAGE_WEIGHT[s] // 2 for s, v in stages.items() if v["status"] == "processing"
    )
    return min(100, done_weight + proc_weight)
