from fastapi import APIRouter
from app.api.v1.endpoints import admin,auth,documents,knowledge_bases,query,users
router=APIRouter(prefix="/api/v1")
for route in (auth.router,users.router,knowledge_bases.router,documents.router,query.router,admin.router):router.include_router(route)
