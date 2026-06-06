from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import router
from app.core.config import settings
from app.core.database import init_db
from app.core.seeder import seed_super_admin
@asynccontextmanager
async def lifespan(app:FastAPI):
 settings.upload_dir.mkdir(parents=True,exist_ok=True);await init_db();await seed_super_admin();yield
app=FastAPI(title=settings.app_name,version="1.0.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=settings.cors_origins,allow_credentials=settings.cors_origins!=["*"],allow_methods=["*"],allow_headers=["*"])
app.include_router(router)
@app.get("/health")
async def health():return {"status":"ok"}
