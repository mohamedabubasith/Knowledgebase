from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories.job_log_repo import JobLogRepo
from app.repositories.prompt_log_repo import PromptLogRepo
from app.services.worker_operations import list_dlq, retry_all_dlq, retry_dlq_entry, worker_health


class AdminService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.job_logs = JobLogRepo(db)
        self.prompt_logs = PromptLogRepo(db)

    async def get_worker_health(self) -> dict:
        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        try:
            health = await worker_health(redis)
        finally:
            await redis.close()

        ids = [UUID(item["document_id"]) for item in health["active_jobs"]]
        if ids:
            from sqlalchemy import select
            from app.models import Document, KnowledgeBase
            documents = {x.id: x for x in (await self.db.scalars(
                select(Document).where(Document.id.in_(ids))
            )).all()}
            kb_ids = [doc.knowledge_base_id for doc in documents.values()]
            kbs = {x.id: x.name for x in (await self.db.scalars(
                select(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids))
            )).all()} if kb_ids else {}
            for item in health["active_jobs"]:
                doc = documents.get(UUID(item["document_id"]))
                item.update({
                    "document_name": doc.original_filename if doc else None,
                    "knowledge_base_name": kbs.get(doc.knowledge_base_id) if doc else None,
                    "processing_stage": doc.processing_stage if doc else None,
                })
        return health

    async def get_job_logs(
        self, page: int, page_size: int, status: str | None, document_id: UUID | None,
        date_from: datetime | None, date_to: datetime | None, job_type: str | None,
    ) -> dict:
        items, total = await self.job_logs.list_filtered(
            page=page, page_size=page_size, status=status, document_id=document_id,
            date_from=date_from, date_to=date_to, job_type=job_type,
        )
        enriched = await self.job_logs.enrich(items)
        return {"items": enriched, "total": total, "page": page, "page_size": page_size}

    async def get_job_log(self, id: UUID) -> dict:
        from fastapi import HTTPException
        item = await self.job_logs.get_by_id(id)
        if not item:
            raise HTTPException(404, "Job log not found")
        return (await self.job_logs.enrich([item]))[0]

    async def get_prompt_logs(
        self, page: int, page_size: int, status: str | None,
        date_from: datetime | None, date_to: datetime | None,
        kb_id: UUID | None, user_id: UUID | None,
        search_type: str | None, min_score: float | None,
    ) -> dict:
        from app.schemas.prompt_log import PromptLogRead
        items, total, users, kbs = await self.prompt_logs.list_filtered(
            page=page, page_size=page_size, status=status, date_from=date_from, date_to=date_to,
            kb_id=kb_id, user_id=user_id, search_type=search_type, min_score=min_score,
        )
        return {
            "items": [
                PromptLogRead.model_validate(item).model_copy(update={
                    "user_email": users.get(item.user_id),
                    "knowledge_base_name": kbs.get(item.knowledge_base_id),
                })
                for item in items
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_prompt_log(self, id: UUID):
        from fastapi import HTTPException
        from app.schemas.prompt_log import PromptLogRead
        item = await self.prompt_logs.get_by_id(id)
        if not item:
            raise HTTPException(404, "Log not found")
        return PromptLogRead.model_validate(item)

    async def delete_prompt_log(self, id: UUID) -> None:
        from fastapi import HTTPException
        item = await self.prompt_logs.get_by_id(id)
        if not item:
            raise HTTPException(404, "Log not found")
        await self.prompt_logs.delete(item)
        await self.db.commit()

    async def get_dlq(self) -> list[dict]:
        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        try:
            return await list_dlq(redis)
        finally:
            await redis.close()

    async def retry_dlq(self, entry_id: str) -> dict:
        from fastapi import HTTPException
        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        try:
            job_id = await retry_dlq_entry(redis, entry_id)
        finally:
            await redis.close()
        if not job_id:
            raise HTTPException(404, "Dead letter job not found")
        return {"job_id": job_id, "status": "queued"}

    async def retry_all_dlq(self) -> dict:
        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        try:
            count = await retry_all_dlq(redis)
        finally:
            await redis.close()
        return {"retried": count}

    async def get_worker_statistics(self) -> dict:
        from app.models import JobLog
        from sqlalchemy import select
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        items = list((await self.db.scalars(select(JobLog).where(JobLog.created_at >= since))).all())
        completed = [i for i in items if i.status == "completed"]
        failed = [i for i in items if i.status == "failed"]
        stage_totals: dict = defaultdict(list)
        file_stats: dict = defaultdict(lambda: {"total": 0, "completed": 0, "failed": 0, "duration_ms": 0})
        per_hour: dict = defaultdict(int)
        for item in items:
            for stage, duration in (item.stage_timings or {}).items():
                stage_totals[stage].append(duration)
            file_type = (item.metadata_ or {}).get("file_type", "unknown")
            file_stats[file_type]["total"] += 1
            file_stats[file_type]["duration_ms"] += item.duration_ms or 0
            if item.status in ("completed", "failed"):
                file_stats[file_type][item.status] += 1
            if item.completed_at:
                per_hour[item.completed_at.replace(minute=0, second=0, microsecond=0).isoformat()] += 1
        total = len(completed) + len(failed)
        return {
            "total_jobs_processed": total,
            "success_rate": round(len(completed) / total, 4) if total else 0,
            "failure_rate": round(len(failed) / total, 4) if total else 0,
            "average_stage_timings": {
                stage: round(sum(v) / len(v), 2) for stage, v in stage_totals.items()
            },
            "by_file_type": {
                k: {**v, "average_duration_ms": round(v["duration_ms"] / v["total"], 2) if v["total"] else 0}
                for k, v in file_stats.items()
            },
            "jobs_completed_per_hour": dict(per_hour),
        }
