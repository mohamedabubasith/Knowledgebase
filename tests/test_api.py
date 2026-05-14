"""
API route tests: ingest, search, documents, status, admin, health.
Uses FastAPI TestClient (httpx.AsyncClient + ASGITransport).
"""
import hashlib
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import API_KEY_HASH, API_KEY_RAW, CHUNK_ID, DOCUMENT_ID, TENANT_ID


# ── App fixture ───────────────────────────────────────────────────────────────

@pytest.fixture
def mock_auth_row():
    return {
        "id": "44444444-4444-4444-4444-444444444444",
        "tenant_id": TENANT_ID,
        "role": "admin",
    }


@pytest.fixture(autouse=True)
def freeze_registry_for_api(frozen_qdrant_registry):
    pass


@pytest.fixture(autouse=True)
def patch_all_infra(mock_pool, mock_conn, mock_auth_row):
    """Patch pool + always authenticate with admin key."""
    mock_conn.fetchrow = AsyncMock(return_value=mock_auth_row)
    mock_conn.fetchval = AsyncMock(return_value=None)
    mock_conn.execute = AsyncMock(return_value="UPDATE 1")
    mock_conn.executemany = AsyncMock(return_value=None)
    mock_conn.fetch = AsyncMock(return_value=[])
    yield


@pytest.fixture
def client(mock_pool):
    from app.main import create_app
    with patch("app.main.init_pool", new=AsyncMock()), \
         patch("app.main.init_minio", new=MagicMock()), \
         patch("app.main.run_startup_probes", new=AsyncMock()), \
         patch("app.main.init_vector_store", new=MagicMock()), \
         patch("app.main.init_parser_pool", new=MagicMock()), \
         patch("app.main.shutdown_workers", new=AsyncMock()), \
         patch("app.main.close_pool", new=AsyncMock()), \
         patch("app.main.asyncio.create_task", return_value=MagicMock()):
        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


AUTH_HEADERS = {"X-Api-Key": API_KEY_RAW}


# ── Health ────────────────────────────────────────────────────────────────────

class TestHealthEndpoint:

    def test_health_returns_200(self, client):
        mock_vs = AsyncMock()
        mock_vs.health_check = AsyncMock(return_value=True)
        with patch("app.api.routes.health.get_vector_store", return_value=mock_vs), \
             patch("app.api.routes.health.get_pool") as mock_gp:
            mock_pool = MagicMock()
            mock_conn = AsyncMock()
            mock_conn.fetchval = AsyncMock(return_value=1)
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_gp.return_value = mock_pool

            with patch("app.api.routes.health.get_client", side_effect=Exception("minio off")):
                resp = client.get("/health")

        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert "registry" in body
        assert "components" in body

    def test_health_no_auth_required(self, client):
        with patch("app.api.routes.health.get_pool") as p, \
             patch("app.api.routes.health.get_vector_store") as vs, \
             patch("app.api.routes.health.get_client", side_effect=Exception()):
            mock_pool = MagicMock()
            mock_conn = AsyncMock()
            mock_conn.fetchval = AsyncMock(return_value=1)
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
            p.return_value = mock_pool
            vs.return_value.health_check = AsyncMock(return_value=True)

            resp = client.get("/health")
        assert resp.status_code == 200


# ── Auth (API key) ─────────────────────────────────────────────────────────────

class TestApiKeyAuth:

    def test_missing_key_returns_403(self, client):
        resp = client.get("/documents")
        assert resp.status_code in (401, 403)

    def test_invalid_key_returns_401(self, client, mock_conn):
        mock_conn.fetchrow = AsyncMock(return_value=None)
        resp = client.get("/documents", headers={"X-Api-Key": "cortex_bad"})
        assert resp.status_code == 401

    def test_valid_key_succeeds(self, client, mock_conn, mock_auth_row):
        mock_conn.fetchrow = AsyncMock(return_value=mock_auth_row)
        mock_conn.fetch = AsyncMock(return_value=[])
        resp = client.get("/documents", headers=AUTH_HEADERS)
        assert resp.status_code == 200


# ── Ingest ────────────────────────────────────────────────────────────────────

class TestIngestEndpoint:

    def test_upload_pdf_accepted(self, client, mock_conn):
        mock_conn.fetchrow = AsyncMock(return_value={
            "id": "44444444-4444-4444-4444-444444444444",
            "tenant_id": TENANT_ID,
            "role": "editor",
        })
        mock_conn.fetchval = AsyncMock(return_value=None)  # no duplicate

        # Minimal valid PDF bytes (enough for magic detection)
        pdf_header = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"

        with patch("app.api.routes.ingest.upload_file", new=AsyncMock(return_value=f"{TENANT_ID}/{DOCUMENT_ID}/test.pdf")), \
             patch("app.api.routes.ingest.ingest_queue") as mock_q, \
             patch("app.api.routes.ingest.filetype.guess", return_value=type("K", (), {"mime": "application/pdf"})()), \
             patch("app.api.routes.ingest.update_stage", new=AsyncMock()):
            mock_q.put = AsyncMock()
            resp = client.post(
                "/ingest/upload",
                files={"file": ("test.pdf", io.BytesIO(pdf_header), "application/pdf")},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 202
        body = resp.json()
        assert "document_id" in body
        assert body["status"] == "pending"

    def test_upload_rejected_if_duplicate(self, client, mock_conn):
        mock_conn.fetchrow = AsyncMock(return_value={
            "id": "44444444-4444-4444-4444-444444444444",
            "tenant_id": TENANT_ID,
            "role": "editor",
        })
        mock_conn.fetchval = AsyncMock(return_value=DOCUMENT_ID)  # duplicate exists

        with patch("app.api.routes.ingest.filetype.guess", return_value=type("K", (), {"mime": "application/pdf"})()):
            resp = client.post(
                "/ingest/upload",
                files={"file": ("test.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 409

    def test_upload_unsupported_mime_rejected(self, client, mock_conn):
        mock_conn.fetchrow = AsyncMock(return_value={
            "id": "44444444-4444-4444-4444-444444444444",
            "tenant_id": TENANT_ID,
            "role": "editor",
        })
        with patch("app.api.routes.ingest.filetype.guess", return_value=type("K", (), {"mime": "image/png"})()):
            resp = client.post(
                "/ingest/upload",
                files={"file": ("image.png", io.BytesIO(b"\x89PNG"), "image/png")},
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 415

    def test_viewer_role_cannot_upload(self, client, mock_conn):
        mock_conn.fetchrow = AsyncMock(return_value={
            "id": "44444444-4444-4444-4444-444444444444",
            "tenant_id": TENANT_ID,
            "role": "viewer",
        })
        resp = client.post(
            "/ingest/upload",
            files={"file": ("test.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 403


# ── Documents ─────────────────────────────────────────────────────────────────

class TestDocumentsEndpoint:

    def test_list_documents_empty(self, client, mock_conn, mock_auth_row):
        mock_conn.fetchrow = AsyncMock(return_value=mock_auth_row)
        mock_conn.fetch = AsyncMock(return_value=[])
        resp = client.get("/documents", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_document_not_found(self, client, mock_conn, mock_auth_row):
        mock_conn.fetchrow = AsyncMock(side_effect=[mock_auth_row, None])
        resp = client.get(f"/documents/{DOCUMENT_ID}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_delete_document_enqueues_purge(self, client, mock_conn, mock_auth_row):
        doc_row = MagicMock()
        doc_row.__getitem__ = lambda s, k: {"id": DOCUMENT_ID, "minio_path": "path/file.pdf"}[k]
        mock_conn.fetchrow = AsyncMock(side_effect=[mock_auth_row, doc_row])
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")

        with patch("app.api.routes.documents.purge_queue") as mock_pq:
            mock_pq.put = AsyncMock()
            resp = client.delete(f"/documents/{DOCUMENT_ID}", headers=AUTH_HEADERS)

        assert resp.status_code == 202
        mock_pq.put.assert_called_once()


# ── Search ────────────────────────────────────────────────────────────────────

class TestSearchEndpoint:

    def test_search_returns_results(self, client, mock_conn, mock_auth_row):
        mock_conn.fetchrow = AsyncMock(return_value=mock_auth_row)

        from app.models.schemas import SearchResponse, SearchResultItem
        mock_response = SearchResponse(
            results=[SearchResultItem(
                chunk_id=CHUNK_ID,
                document_id=DOCUMENT_ID,
                text="fox jumps",
                score=0.9,
                page_number=1,
                file_path="path/file.pdf",
            )],
            total=1,
            search_mode_used="hybrid",
            query_ms=5.2,
        )

        with patch("app.api.routes.search.search", new=AsyncMock(return_value=mock_response)):
            resp = client.get("/search?q=fox", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["search_mode_used"] == "hybrid"

    def test_search_empty_query_rejected(self, client):
        resp = client.get("/search?q=", headers=AUTH_HEADERS)
        assert resp.status_code == 422

    def test_search_invalid_mode_rejected(self, client, mock_conn, mock_auth_row):
        mock_conn.fetchrow = AsyncMock(return_value=mock_auth_row)
        resp = client.get("/search?q=test&mode=invalid", headers=AUTH_HEADERS)
        assert resp.status_code == 422


# ── Status ────────────────────────────────────────────────────────────────────

class TestStatusEndpoint:

    def test_list_status_returns_list(self, client, mock_conn, mock_auth_row):
        mock_conn.fetchrow = AsyncMock(return_value=mock_auth_row)

        with patch("app.api.routes.status.list_pipeline_statuses", new=AsyncMock(return_value=[])):
            resp = client.get("/status", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_status_not_found(self, client, mock_conn, mock_auth_row):
        mock_conn.fetchrow = AsyncMock(return_value=mock_auth_row)

        with patch("app.api.routes.status.get_pipeline_status", new=AsyncMock(return_value=None)):
            resp = client.get(f"/status/{DOCUMENT_ID}", headers=AUTH_HEADERS)

        assert resp.status_code == 404

    def test_get_status_returns_pipeline(self, client, mock_conn, mock_auth_row):
        from app.core.pipeline import STAGES
        mock_conn.fetchrow = AsyncMock(return_value=mock_auth_row)

        pipeline_data = {
            "document_id": DOCUMENT_ID,
            "filename": "test.pdf",
            "overall_status": "indexed",
            "progress_pct": 100,
            "file_size": 1024,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "stages": {s: {"status": "done", "started_at": None, "completed_at": None, "detail": {}} for s in STAGES},
        }
        with patch("app.api.routes.status.get_pipeline_status", new=AsyncMock(return_value=pipeline_data)):
            resp = client.get(f"/status/{DOCUMENT_ID}", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["progress_pct"] == 100
        assert set(body["stages"].keys()) == set(STAGES)


# ── Admin ─────────────────────────────────────────────────────────────────────

class TestAdminEndpoint:

    def test_create_api_key_returns_raw_key(self, client, mock_conn, mock_auth_row):
        mock_conn.fetchrow = AsyncMock(return_value=mock_auth_row)
        resp = client.post(
            "/admin/api-keys",
            json={"label": "test-key", "role": "editor"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["raw_key"].startswith("cortex_")
        assert body["role"] == "editor"

    def test_create_key_invalid_role_rejected(self, client, mock_conn, mock_auth_row):
        mock_conn.fetchrow = AsyncMock(return_value=mock_auth_row)
        resp = client.post(
            "/admin/api-keys",
            json={"label": "bad", "role": "superadmin"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400

    def test_revoke_key_not_found(self, client, mock_conn, mock_auth_row):
        mock_conn.fetchrow = AsyncMock(return_value=mock_auth_row)
        mock_conn.execute = AsyncMock(return_value="UPDATE 0")
        resp = client.delete(f"/admin/api-keys/nonexistent-id", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_revoke_key_success(self, client, mock_conn, mock_auth_row):
        mock_conn.fetchrow = AsyncMock(return_value=mock_auth_row)
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        resp = client.delete(f"/admin/api-keys/{DOCUMENT_ID}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["status"] == "revoked"

    def test_viewer_cannot_access_admin(self, client, mock_conn):
        mock_conn.fetchrow = AsyncMock(return_value={
            "id": "44444444-4444-4444-4444-444444444444",
            "tenant_id": TENANT_ID,
            "role": "viewer",
        })
        resp = client.post(
            "/admin/api-keys",
            json={"label": "x", "role": "viewer"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 403

    def test_create_tenant(self, client, mock_conn, mock_auth_row):
        mock_conn.fetchrow = AsyncMock(return_value=mock_auth_row)
        resp = client.post(
            "/admin/tenants",
            json={"name": "Acme Corp"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Acme Corp"
        assert "tenant_id" in body
