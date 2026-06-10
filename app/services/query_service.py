import time
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import PromptLog, PromptStatus, User
from app.repositories.prompt_log_repo import PromptLogRepo
from app.schemas.query import QueryRequest, QueryResponse, SearchResult
from app.services.kb_service import KBService
from app.services.llm_service import answer_question
from app.services.search_service import hybrid_search


class QueryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.kb_svc = KBService(db)
        self.logs = PromptLogRepo(db)

    async def search(self, body: QueryRequest, user: User) -> list[SearchResult]:
        await self.kb_svc.get(body.knowledge_base_id, user)
        sources, _ = await hybrid_search(
            self.db, body.knowledge_base_id, body.prompt,
            body.top_k, body.similarity_threshold, body.search_type,
        )
        return sources

    async def query(self, body: QueryRequest, user: User) -> QueryResponse:
        start = time.perf_counter()
        await self.kb_svc.get(body.knowledge_base_id, user)
        sources: list = []
        total: int = 0
        try:
            sources, total = await hybrid_search(
                self.db, body.knowledge_base_id, body.prompt,
                body.top_k, body.similarity_threshold, body.search_type,
            )
            response, tokens = await answer_question(body.prompt, sources)
            latency = (time.perf_counter() - start) * 1000
            log = await self.logs.create(
                user_id=user.id,
                knowledge_base_id=body.knowledge_base_id,
                prompt=body.prompt,
                response=response,
                sources=[
                    {**s, "chunk_id": str(s["chunk_id"]), "document_id": str(s["document_id"]),
                     "knowledge_base_id": str(s["knowledge_base_id"])}
                    for s in sources
                ],
                tokens_used=tokens,
                latency_ms=int(latency),
                model_used=settings.tabular_sql_model,
                status=PromptStatus.success,
                top_k_used=body.top_k,
                similarity_threshold=body.similarity_threshold,
                total_sources_found=total,
                search_type=body.search_type,
                metadata_={},
            )
            await self.db.commit()
            return QueryResponse(
                query_id=log.id,
                prompt=body.prompt,
                response=response,
                sources=sources if body.include_sources else [],
                total_sources_found=total,
                top_k_used=body.top_k,
                similarity_threshold=body.similarity_threshold,
                search_type=body.search_type,
                tokens_used=tokens,
                latency_ms=latency,
                model_used=settings.tabular_sql_model,
                created_at=log.created_at or datetime.now(timezone.utc),
            )
        except Exception as exc:
            await self.db.rollback()
            await self.logs.create(
                user_id=user.id,
                knowledge_base_id=body.knowledge_base_id,
                prompt=body.prompt,
                response="",
                sources=[],
                latency_ms=int((time.perf_counter() - start) * 1000),
                model_used=settings.tabular_sql_model,
                status=PromptStatus.failed,
                error=str(exc),
                top_k_used=body.top_k,
                similarity_threshold=body.similarity_threshold,
                total_sources_found=total,
                search_type=body.search_type,
                metadata_={},
            )
            await self.db.commit()
            raise
