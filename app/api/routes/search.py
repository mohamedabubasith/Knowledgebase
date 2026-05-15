from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import AuthContext, get_auth
from app.models.schemas import SearchMode, SearchRequest, SearchResponse
from app.search.engine import search

router = APIRouter(prefix="/search", tags=["search"])


@router.get(
    "",
    response_model=SearchResponse,
    summary="Search documents (GET)",
    description=(
        "Search ingested documents using your choice of search strategy.\n\n"
        "**Search modes:**\n"
        "- `hybrid` — vector + keyword combined. Best quality. **Default.**\n"
        "- `vector_only` — semantic/conceptual search. Good for paraphrases and multilingual queries.\n"
        "- `lexical_only` — exact keyword match (BM25/FTS). Fast. Good for codes, IDs, exact terms.\n\n"
        "Results are ranked by relevance score (0–1). Use `min_score` to filter low-quality matches."
    ),
)
async def search_documents_get(
    auth: Annotated[AuthContext, Depends(get_auth)],
    q: str = Query(min_length=1, max_length=2000, description="Search query text"),
    mode: SearchMode = Query(default=SearchMode.hybrid, description="Search strategy"),
    top_k: int = Query(default=10, ge=1, le=100, description="Number of results"),
    min_score: float = Query(default=0.0, ge=0.0, le=1.0, description="Minimum score threshold"),
    document_id: Optional[str] = Query(default=None, description="Scope to specific document"),
) -> SearchResponse:
    return await search(
        query=q,
        tenant_id=auth.tenant_id,
        mode=mode.value,
        top_k=top_k,
        min_score=min_score,
        document_id=document_id,
    )


@router.post(
    "",
    response_model=SearchResponse,
    summary="Search documents (POST)",
    description=(
        "Same as GET /search but accepts a JSON body — easier to use from frontend/UI.\n\n"
        "**Search modes:**\n"
        "- `hybrid` — vector + keyword combined. Best quality. **Default.**\n"
        "- `vector_only` — semantic/conceptual search. Good for paraphrases and multilingual queries.\n"
        "- `lexical_only` — exact keyword match (BM25/FTS). Fast. Good for codes, IDs, exact terms.\n\n"
        "Results are ranked by relevance score (0–1). Use `min_score` to filter low-quality matches."
    ),
)
async def search_documents_post(
    auth: Annotated[AuthContext, Depends(get_auth)],
    body: SearchRequest,
) -> SearchResponse:
    return await search(
        query=body.query,
        tenant_id=auth.tenant_id,
        mode=body.mode.value,
        top_k=body.top_k,
        min_score=body.min_score,
        document_id=body.document_id,
    )
