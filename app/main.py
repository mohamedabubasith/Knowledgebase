from contextlib import asynccontextmanager
import asyncio
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import router
from app.core.config import settings
from app.core.database import init_db
from app.core.seeder import seed_super_admin
from app.core.embedding import load_embedding_model
from app.core.minio import init_minio
from app.core.qdrant import init_qdrant
log=structlog.get_logger(__name__)
@asynccontextmanager
async def lifespan(app:FastAPI):
 await init_db()
 await asyncio.to_thread(load_embedding_model)
 await init_qdrant()
 await init_minio()
 await seed_super_admin()
 log.info("kb_platform_ready")
 yield
app=FastAPI(title=settings.app_name,version="1.0.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=settings.cors_origins,allow_credentials=settings.cors_origins!=["*"],allow_methods=["*"],allow_headers=["*"])
app.include_router(router)
@app.get("/health")
async def health():return {"status":"ok"}
