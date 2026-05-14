"""
Tests for MinIO storage client.
Minio SDK calls mocked.
"""
import io
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import DOCUMENT_ID, TENANT_ID


@pytest.fixture
def mock_minio_client():
    client = MagicMock()
    client.bucket_exists.return_value = True
    client.put_object.return_value = None
    client.remove_object.return_value = None

    response_mock = MagicMock()
    response_mock.read.return_value = b"file content"
    response_mock.close.return_value = None
    response_mock.release_conn.return_value = None
    client.get_object.return_value = response_mock

    return client


@pytest.fixture(autouse=True)
def patch_minio(mock_minio_client):
    import app.storage.minio_client as mc
    mc._client = mock_minio_client
    yield
    mc._client = None


class TestMinioInit:

    def test_init_creates_bucket_if_missing(self):
        client = MagicMock()
        client.bucket_exists.return_value = False
        client.make_bucket.return_value = None

        with patch("app.storage.minio_client.Minio", return_value=client), \
             patch("app.core.config.settings") as s:
            s.minio_endpoint = "localhost:9000"
            s.minio_access_key = "admin"
            s.minio_secret_key = "admin"
            s.minio_secure = False
            s.minio_bucket_raw = "raw-documents"

            import app.storage.minio_client as mc
            mc._client = None
            mc.init_minio()
            client.make_bucket.assert_called_once_with("raw-documents")

    def test_get_client_raises_if_not_init(self):
        import app.storage.minio_client as mc
        mc._client = None
        with pytest.raises(RuntimeError, match="not initialized"):
            mc.get_client()
        mc._client = MagicMock()


class TestUploadFile:

    async def test_upload_returns_correct_path(self, mock_minio_client):
        from app.storage.minio_client import upload_file

        path = await upload_file(TENANT_ID, DOCUMENT_ID, "test.pdf", b"data", "application/pdf")
        assert path == f"{TENANT_ID}/{DOCUMENT_ID}/test.pdf"
        mock_minio_client.put_object.assert_called_once()

    async def test_upload_uses_correct_bucket(self, mock_minio_client):
        with patch("app.core.config.settings") as s:
            s.minio_bucket_raw = "raw-documents"
            from app.storage.minio_client import upload_file
            await upload_file(TENANT_ID, DOCUMENT_ID, "x.pdf", b"data", "application/pdf")
            call_kwargs = mock_minio_client.put_object.call_args[1]
            assert call_kwargs["bucket_name"] == "raw-documents"


class TestDownloadFile:

    async def test_download_returns_bytes(self, mock_minio_client):
        from app.storage.minio_client import download_file
        data = await download_file(f"{TENANT_ID}/{DOCUMENT_ID}/test.pdf")
        assert data == b"file content"
        mock_minio_client.get_object.assert_called_once()


class TestDeleteFile:

    async def test_delete_calls_remove_object(self, mock_minio_client):
        from app.storage.minio_client import delete_file
        await delete_file(f"{TENANT_ID}/{DOCUMENT_ID}/test.pdf")
        mock_minio_client.remove_object.assert_called_once()

    async def test_delete_path_passed_correctly(self, mock_minio_client):
        from app.storage.minio_client import delete_file
        path = f"{TENANT_ID}/{DOCUMENT_ID}/test.pdf"
        await delete_file(path)
        call_kwargs = mock_minio_client.remove_object.call_args[1]
        assert call_kwargs["object_name"] == path
