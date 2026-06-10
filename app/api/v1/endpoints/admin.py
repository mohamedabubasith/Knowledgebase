from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.dependencies import require_super_admin
from app.services.admin_service import AdminService

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_super_admin)])


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import func, select
    from app.models import Chunk, Document, KnowledgeBase, PromptLog, User
    from datetime import timezone

    async def count(m):
        return await db.scalar(select(func.count()).select_from(m))

    today = datetime.now(timezone.utc).date()
    return {
        "knowledge_bases": await count(KnowledgeBase),
        "documents": await count(Document),
        "chunks": await count(Chunk),
        "users": await count(User),
        "prompts_today": await db.scalar(
            select(func.count()).select_from(PromptLog).where(func.date(PromptLog.created_at) == today)
        ),
    }


@router.get("/prompt-logs")
async def prompt_logs(
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
    status: str | None = None, date_from: datetime | None = None, date_to: datetime | None = None,
    kb_id: UUID | None = None, user_id: UUID | None = None,
    search_type: str | None = None, min_score: float | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await AdminService(db).get_prompt_logs(
        page=page, page_size=page_size, status=status, date_from=date_from, date_to=date_to,
        kb_id=kb_id, user_id=user_id, search_type=search_type, min_score=min_score,
    )


@router.get("/prompt-logs/{id}")
async def prompt_log_detail(id: UUID, db: AsyncSession = Depends(get_db)):
    return await AdminService(db).get_prompt_log(id)


@router.delete("/prompt-logs/{id}", status_code=204)
async def delete_prompt_log(id: UUID, db: AsyncSession = Depends(get_db)):
    await AdminService(db).delete_prompt_log(id)


@router.get("/worker/health")
async def worker_health(db: AsyncSession = Depends(get_db)):
    return await AdminService(db).get_worker_health()


@router.get("/worker/job-logs")
async def job_logs(
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
    status: str | None = None, document_id: UUID | None = None,
    date_from: datetime | None = None, date_to: datetime | None = None,
    job_type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await AdminService(db).get_job_logs(
        page=page, page_size=page_size, status=status, document_id=document_id,
        date_from=date_from, date_to=date_to, job_type=job_type,
    )


@router.get("/worker/job-logs/{id}")
async def job_log_detail(id: UUID, db: AsyncSession = Depends(get_db)):
    return await AdminService(db).get_job_log(id)


@router.get("/worker/statistics")
async def worker_statistics(db: AsyncSession = Depends(get_db)):
    return await AdminService(db).get_worker_statistics()


@router.get("/worker/dead-letter")
async def dead_letter_jobs(db: AsyncSession = Depends(get_db)):
    return await AdminService(db).get_dlq()


@router.post("/worker/dead-letter/{entry_id}/retry")
async def retry_dead_letter(entry_id: str, db: AsyncSession = Depends(get_db)):
    return await AdminService(db).retry_dlq(entry_id)


@router.post("/worker/dead-letter/retry-all")
async def retry_all_dead_letter(db: AsyncSession = Depends(get_db)):
    return await AdminService(db).retry_all_dlq()
