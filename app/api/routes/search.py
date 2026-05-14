from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import AuthContext, get_auth
from app.models.schemas import SearchResponse
from app.search.engine import search

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResponse)
async def search_documents(
    auth: Annotated[AuthContext, Depends(get_auth)],
    q: str = Query(min_length=1, max_length=2000),
    mode: str = Query(default="hybrid", pattern="^(hybrid|vector_only|lexical_only)$"),
    top_k: int = Query(default=10, ge=1, le=100),
    document_id: Optional[str] = Query(default=None),
) -> SearchResponse:
    return await search(
        query=q,
        tenant_id=auth.tenant_id,
        mode=mode,
        top_k=top_k,
        document_id=document_id,
    )
