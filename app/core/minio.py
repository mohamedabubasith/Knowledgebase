import asyncio
import io
from datetime import timedelta

import boto3
from botocore.client import Config
import structlog

from app.core.config import settings

log = structlog.get_logger(__name__)
_client = None


def _get_client():
    global _client
    if _client is None:
        scheme = "https" if settings.minio_use_ssl else "http"
        _client = boto3.client(
            "s3",
            endpoint_url=f"{scheme}://{settings.minio_endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            config=Config(signature_version="s3v4"),
        )
    return _client


async def init_minio() -> None:
    client = _get_client()
    buckets = await asyncio.to_thread(client.list_buckets)
    if settings.minio_bucket not in {bucket["Name"] for bucket in buckets.get("Buckets", [])}:
        await asyncio.to_thread(client.create_bucket, Bucket=settings.minio_bucket)
    log.info("minio_ready", endpoint=settings.minio_endpoint, bucket=settings.minio_bucket)


async def upload_file(file_bytes: bytes, object_key: str, content_type: str) -> str:
    await asyncio.to_thread(
        _get_client().upload_fileobj,
        io.BytesIO(file_bytes),
        settings.minio_bucket,
        object_key,
        ExtraArgs={"ContentType": content_type},
    )
    return object_key


async def download_file(object_key: str) -> bytes:
    response = await asyncio.to_thread(_get_client().get_object, Bucket=settings.minio_bucket, Key=object_key)
    return await asyncio.to_thread(response["Body"].read)


async def get_presigned_url(object_key: str, expires: int = 3600) -> str:
    return await asyncio.to_thread(
        _get_client().generate_presigned_url,
        "get_object",
        Params={"Bucket": settings.minio_bucket, "Key": object_key},
        ExpiresIn=expires,
    )


async def delete_file(object_key: str) -> bool:
    await asyncio.to_thread(_get_client().delete_object, Bucket=settings.minio_bucket, Key=object_key)
    return True
