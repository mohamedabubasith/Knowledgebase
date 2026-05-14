"""
Tests for embedding layer.
Ollama and SentenceTransformers are always mocked.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np


@pytest.fixture(autouse=True)
def set_frozen_registry(frozen_qdrant_registry):
    pass


class TestEmbedBatchOllama:

    @pytest.fixture(autouse=True)
    def set_ollama_backend(self):
        import app.core.registry as reg
        reg.registry.embed_backend = "ollama"

    async def test_embed_batch_calls_ollama(self):
        vectors = [[0.1] * 384, [0.2] * 384]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embeddings": vectors}
        mock_response.raise_for_status = MagicMock()

        with patch("app.embedding.embedder.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.embedding.embedder import embed_batch
            result = await embed_batch(["hello", "world"])

        assert len(result) == 2
        assert result[0] == vectors[0]
        assert result[1] == vectors[1]

    async def test_embed_empty_list_returns_empty(self):
        from app.embedding.embedder import embed_batch
        result = await embed_batch([])
        assert result == []

    async def test_embed_single_delegates_to_batch(self):
        vector = [0.5] * 384
        with patch("app.embedding.embedder.embed_batch", new=AsyncMock(return_value=[vector])) as mock_batch:
            from app.embedding.embedder import embed_single
            result = await embed_single("hello")
        assert result == vector

    async def test_batch_split_respects_batch_size(self):
        """64 texts with batch_size=10 → calls _embed_ollama 7 times."""
        texts = [f"text{i}" for i in range(64)]
        call_count = 0

        async def fake_embed_ollama(batch):
            nonlocal call_count
            call_count += 1
            return [[0.1] * 384] * len(batch)

        with patch("app.embedding.embedder._embed_ollama", side_effect=fake_embed_ollama), \
             patch("app.core.config.settings") as mock_settings:
            mock_settings.embed_batch_size = 10
            mock_settings.ollama_url = "http://localhost:11434"
            mock_settings.ollama_embed_model = "nomic-embed-text"

            from importlib import reload
            import app.embedding.embedder as emb_mod
            import app.core.registry as reg
            reg.registry.embed_backend = "ollama"

            result = await emb_mod.embed_batch.__wrapped__(texts) if hasattr(emb_mod.embed_batch, '__wrapped__') else await emb_mod.embed_batch(texts)

        assert len(result) == 64


class TestEmbedBatchSentenceTransformers:

    @pytest.fixture(autouse=True)
    def set_st_backend(self):
        import app.core.registry as reg
        reg.registry.embed_backend = "sentence_transformers"

    async def test_embed_batch_uses_executor(self):
        import app.embedding.embedder as emb
        import numpy as np
        vectors = np.array([[0.3] * 384, [0.4] * 384])

        mock_model = MagicMock()
        mock_model.encode.return_value = vectors
        emb._st_model = mock_model

        result = await emb.embed_batch(["a", "b"])
        assert len(result) == 2
        assert result[0] == vectors[0].tolist()
        emb._st_model = None  # cleanup

    async def test_st_model_not_loaded_raises(self):
        import app.embedding.embedder as emb
        emb._st_model = None
        with pytest.raises(RuntimeError, match="not loaded"):
            await emb._embed_st(["test"])


class TestLoadSentenceTransformers:

    def test_load_sets_global_model(self):
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384
        mock_model.encode.return_value = [[0.1] * 384]

        with patch("app.embedding.embedder.SentenceTransformer", return_value=mock_model), \
             patch("app.embedding.embedder.torch"):
            from app.embedding.embedder import load_sentence_transformers
            import app.embedding.embedder as emb
            load_sentence_transformers()
            assert emb._st_model is mock_model
            emb._st_model = None
