"""
MinIO client — streaming upload, no local disk buffering.
Pre-initialized at startup, reused across all requests.
"""
import asyncio
import io
from concurrent.futures import ThreadPoolExecutor

import structlog
from minio import Minio
from minio.error import S3Error

from app.core.config import settings

log = structlog.get_logger(__name__)

_client: Minio | None = None
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="minio")


def init_minio() -> None:
    global _client
    _client = Minio(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    for bucket in [settings.minio_bucket_raw]:
        if not _client.bucket_exists(bucket):
            _client.make_bucket(bucket)
            log.info("minio_bucket_created", bucket=bucket)
    log.info("minio_ready", endpoint=settings.minio_endpoint)


def get_client() -> Minio:
    if _client is None:
        raise RuntimeError("MinIO not initialized")
    return _client


async def upload_file(
    tenant_id: str,
    document_id: str,
    filename: str,
    data: bytes,
    content_type: str,
) -> str:
    """Upload bytes to MinIO. Returns minio_path."""
    path = f"{tenant_id}/{document_id}/{filename}"
    loop = asyncio.get_event_loop()

    def _upload():
        get_client().put_object(
            bucket_name=settings.minio_bucket_raw,
            object_name=path,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

    await loop.run_in_executor(_executor, _upload)
    log.info("minio_upload_ok", path=path, size=len(data))
    return path


async def download_file(minio_path: str) -> bytes:
    """Download file bytes from MinIO."""
    loop = asyncio.get_event_loop()

    def _download():
        response = get_client().get_object(
            bucket_name=settings.minio_bucket_raw,
            object_name=minio_path,
        )
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    return await loop.run_in_executor(_executor, _download)


async def delete_file(minio_path: str) -> None:
    loop = asyncio.get_event_loop()

    def _delete():
        get_client().remove_object(
            bucket_name=settings.minio_bucket_raw,
            object_name=minio_path,
        )

    await loop.run_in_executor(_executor, _delete)
    log.info("minio_delete_ok", path=minio_path)
