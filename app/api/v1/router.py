from fastapi import APIRouter
from app.api.v1.endpoints import admin, auth, documents, knowledge_bases, query, tenants, users, workspace

router = APIRouter(prefix="/api/v1")
for route in (auth.router, users.router, knowledge_bases.router, documents.router, query.router, admin.router, tenants.router, workspace.router):
    router.include_router(route)
