from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models import User
from app.schemas.query import QueryRequest, QueryResponse, SearchResult
from app.services.query_service import QueryService

router = APIRouter(prefix="/query", tags=["query"])


@router.post("/search", response_model=list[SearchResult])
async def search(body: QueryRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await QueryService(db).search(body, user)


@router.post("", response_model=QueryResponse)
async def query(body: QueryRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await QueryService(db).query(body, user)
