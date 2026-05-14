"""
Tests for startup probes — all HTTP calls mocked.
Verifies registry fields set correctly per probe outcomes.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def fresh_registry():
    import app.core.registry as reg
    from app.core.registry import ServiceRegistry
    reg.registry = ServiceRegistry()
    yield
    reg.registry = ServiceRegistry()


class TestParseBackendProbe:

    async def test_selects_unstructured_api_when_reachable(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("app.core.startup.httpx.AsyncClient") as cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            cls.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("app.core.config.settings") as s:
                s.unstructured_api_url = "http://unstructured:8000"
                s.unstructured_api_key = ""
                s.unstructured_local_url = ""
                from app.core.startup import _probe_unstructured_api
                result = await _probe_unstructured_api()

        assert result is True

    async def test_returns_false_when_unreachable(self):
        with patch("app.core.startup.httpx.AsyncClient") as cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("connect error"))
            cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            cls.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("app.core.config.settings") as s:
                s.unstructured_api_url = "http://bad"
                from app.core.startup import _probe_unstructured_api
                result = await _probe_unstructured_api()

        assert result is False

    async def test_returns_false_when_url_empty(self):
        with patch("app.core.config.settings") as s:
            s.unstructured_api_url = ""
            from app.core.startup import _probe_unstructured_api
            result = await _probe_unstructured_api()
        assert result is False


class TestEmbedBackendProbe:

    async def test_selects_ollama_when_reachable(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"embeddings": [[0.1] * 384]}

        with patch("app.core.startup.httpx.AsyncClient") as cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            cls.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("app.core.config.settings") as s:
                s.ollama_url = "http://ollama:11434"
                s.ollama_embed_model = "nomic-embed-text"
                from app.core.startup import _probe_ollama
                ok, dim, model = await _probe_ollama()

        assert ok is True
        assert dim == 384
        assert model == "nomic-embed-text"

    async def test_returns_false_when_ollama_down(self):
        with patch("app.core.startup.httpx.AsyncClient") as cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("timeout"))
            cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            cls.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("app.core.config.settings") as s:
                s.ollama_url = "http://bad"
                s.ollama_embed_model = "model"
                from app.core.startup import _probe_ollama
                ok, dim, model = await _probe_ollama()

        assert ok is False
        assert dim == 0

    def test_probe_sentence_transformers_returns_dim(self):
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384

        with patch("app.core.startup.SentenceTransformer", return_value=mock_model), \
             patch("app.core.startup.torch"), \
             patch("app.core.config.settings") as s:
            s.st_model = "all-MiniLM-L6-v2"
            from app.core.startup import _probe_sentence_transformers
            dim, model_name = _probe_sentence_transformers()

        assert dim == 384
        assert "MiniLM" in model_name


class TestVectorBackendProbe:

    async def test_selects_qdrant_when_reachable(self):
        mock_client = AsyncMock()
        mock_client.get_collections = AsyncMock(return_value=MagicMock(collections=[]))
        mock_client.create_collection = AsyncMock()
        mock_client.close = AsyncMock()

        with patch("app.core.startup.AsyncQdrantClient", return_value=mock_client), \
             patch("app.core.config.settings") as s:
            s.qdrant_url = "http://qdrant:6333"
            s.qdrant_api_key = ""
            s.qdrant_collection = "cortex_kb"
            from app.core.startup import _probe_qdrant
            result = await _probe_qdrant(384)

        assert result is True

    async def test_returns_false_when_qdrant_down(self):
        with patch("app.core.startup.AsyncQdrantClient") as cls:
            cls.return_value.get_collections = AsyncMock(side_effect=Exception("refused"))
            with patch("app.core.config.settings") as s:
                s.qdrant_url = "http://bad"
                s.qdrant_api_key = ""
                s.qdrant_collection = "cortex_kb"
                from app.core.startup import _probe_qdrant
                result = await _probe_qdrant(384)

        assert result is False


class TestFullStartupProbes:

    async def test_registry_frozen_after_probes(self):
        with patch("app.core.startup._probe_unstructured_api", new=AsyncMock(return_value=False)), \
             patch("app.core.startup._probe_local_unstructured", new=AsyncMock(return_value=False)), \
             patch("app.core.startup._probe_ollama", new=AsyncMock(return_value=(False, 0, ""))), \
             patch("app.core.startup._probe_qdrant", new=AsyncMock(return_value=False)), \
             patch("app.core.startup._init_chroma", new=MagicMock()), \
             patch("app.core.startup._probe_sentence_transformers", return_value=(384, "all-MiniLM-L6-v2")):
            import asyncio
            with patch("asyncio.get_event_loop") as mock_loop:
                loop = MagicMock()
                loop.run_in_executor = AsyncMock(return_value=(384, "all-MiniLM-L6-v2"))
                mock_loop.return_value = loop

                from app.core.startup import run_startup_probes
                import app.core.registry as reg
                await run_startup_probes()

                assert reg.registry.is_frozen()

    async def test_all_fallbacks_set_local_parsers_st_chroma(self):
        with patch("app.core.startup._probe_unstructured_api", new=AsyncMock(return_value=False)), \
             patch("app.core.startup._probe_local_unstructured", new=AsyncMock(return_value=False)), \
             patch("app.core.startup._probe_ollama", new=AsyncMock(return_value=(False, 0, ""))), \
             patch("app.core.startup._probe_qdrant", new=AsyncMock(return_value=False)), \
             patch("app.core.startup._init_chroma", new=MagicMock()):
            with patch("asyncio.get_event_loop") as mock_loop:
                loop = MagicMock()
                loop.run_in_executor = AsyncMock(return_value=(384, "all-MiniLM-L6-v2"))
                mock_loop.return_value = loop

                from app.core.startup import run_startup_probes
                import app.core.registry as reg
                await run_startup_probes()

                assert reg.registry.parse_backend == "local_parsers"
                assert reg.registry.embed_backend == "sentence_transformers"
                assert reg.registry.vector_backend == "chroma"
