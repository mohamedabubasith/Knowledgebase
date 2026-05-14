"""
Pipeline status endpoints.

GET  /status                      - list all docs + pipeline stages (paginated)
GET  /status/{document_id}        - detailed pipeline for one doc
GET  /status/stream               - SSE stream: ALL pipeline events for tenant
GET  /status/{document_id}/stream - SSE stream: events for specific doc only
"""
import asyncio
import json
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import AuthContext, get_auth
from app.core.pipeline import (
    get_pipeline_status,
    list_pipeline_statuses,
    subscribe,
    unsubscribe,
)

router = APIRouter(prefix="/status", tags=["status"])
log = structlog.get_logger(__name__)


@router.get("")
async def list_status(
    auth: Annotated[AuthContext, Depends(get_auth)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: Optional[str] = Query(default=None),
) -> list[dict]:
    return await list_pipeline_statuses(
        tenant_id=auth.tenant_id,
        limit=limit,
        offset=offset,
        status_filter=status,
    )


@router.get("/stream")
async def stream_all(
    auth: Annotated[AuthContext, Depends(get_auth)],
) -> StreamingResponse:
    """SSE stream — all pipeline events for this tenant."""
    return StreamingResponse(
        _sse_generator(auth.tenant_id, document_id=None),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


@router.get("/{document_id}")
async def get_status(
    document_id: str,
    auth: Annotated[AuthContext, Depends(get_auth)],
) -> dict:
    result = await get_pipeline_status(document_id, auth.tenant_id)
    if not result:
        raise HTTPException(status_code=404, detail="Document not found")
    return result


@router.get("/{document_id}/stream")
async def stream_document(
    document_id: str,
    auth: Annotated[AuthContext, Depends(get_auth)],
) -> StreamingResponse:
    """SSE stream — events for one document only."""
    return StreamingResponse(
        _sse_generator(auth.tenant_id, document_id=document_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _sse_generator(tenant_id: str, document_id: Optional[str]):
    """
    Yield SSE-formatted events.
    Filters by document_id if provided.
    Sends heartbeat every 15s to keep connection alive.
    """
    q = await subscribe(tenant_id)
    try:
        # Send current snapshot on connect
        if document_id:
            snapshot = await get_pipeline_status(document_id, tenant_id)
            if snapshot:
                yield _sse_event("snapshot", snapshot)
        else:
            snapshots = await list_pipeline_statuses(tenant_id, limit=50)
            yield _sse_event("snapshot", {"documents": snapshots})

        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=15.0)
                if document_id and event.get("document_id") != document_id:
                    continue
                yield _sse_event("pipeline_update", event)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"  # SSE comment — keeps connection alive
    except asyncio.CancelledError:
        pass
    finally:
        await unsubscribe(tenant_id, q)


def _sse_event(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
