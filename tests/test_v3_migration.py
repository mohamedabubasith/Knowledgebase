from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.embedding import get_sparse_embedding
from app.core.config import settings
from app.core.qdrant import ChunkVector, _with_port, collection_name, create_collection, upsert_chunks
from app.schemas.query import QueryRequest


def test_sparse_embedding_is_stable_and_normalized():
    first = get_sparse_embedding("alpha alpha beta")
    second = get_sparse_embedding("alpha alpha beta")

    assert first == second
    assert len(first) == 2
    assert max(first.values()) <= 1.0


def test_query_request_defaults_to_hybrid():
    request = QueryRequest(prompt="question", knowledge_base_id=uuid4())

    assert request.search_type == "hybrid"
    assert request.similarity_threshold == 0.3
    assert request.include_sources is True


def test_qdrant_ingress_url_gets_http_port():
    assert _with_port("http://qdrant.example.com") == "http://qdrant.example.com:80"
    assert _with_port("https://qdrant.example.com") == "https://qdrant.example.com:443"


@pytest.mark.asyncio
async def test_create_collection_uses_per_kb_name():
    client = AsyncMock()
    client.collection_exists.return_value = False

    with patch("app.core.qdrant.get_client", return_value=client):
        await create_collection("abc")

    assert collection_name("abc") == "kb_abc"
    assert client.create_collection.call_args.kwargs["collection_name"] == "kb_abc"
    assert client.create_collection.call_args.kwargs["vectors_config"]["dense"].size == settings.embed_dimension


@pytest.mark.asyncio
async def test_upsert_chunks_uses_named_dense_and_sparse_vectors():
    client = AsyncMock()
    client.collection_exists.return_value = True
    chunk = ChunkVector(id=str(uuid4()), dense=[0.0] * settings.embed_dimension, sparse={1: 0.5}, payload={"content": "text"})

    with patch("app.core.qdrant.get_client", return_value=client):
        await upsert_chunks("abc", [chunk])

    point = client.upsert.call_args.kwargs["points"][0]
    assert set(point.vector) == {"dense", "sparse"}
