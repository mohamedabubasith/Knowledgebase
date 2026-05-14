"""
Tests for ServiceRegistry: freeze semantics, as_dict, defaults.
"""
import pytest
from app.core.registry import ServiceRegistry


class TestServiceRegistry:

    def test_default_state_not_frozen(self):
        reg = ServiceRegistry()
        assert not reg.is_frozen()

    def test_freeze_locks_registry(self):
        reg = ServiceRegistry()
        reg.freeze()
        assert reg.is_frozen()

    def test_as_dict_contains_all_fields(self):
        reg = ServiceRegistry()
        d = reg.as_dict()
        assert "parse_backend" in d
        assert "embed_backend" in d
        assert "embed_dimension" in d
        assert "embed_model_name" in d
        assert "vector_backend" in d
        assert "search_mode" in d

    def test_defaults(self):
        reg = ServiceRegistry()
        assert reg.parse_backend == "local_parsers"
        assert reg.embed_backend == "sentence_transformers"
        assert reg.embed_dimension == 384
        assert reg.vector_backend == "chroma"
        assert reg.search_mode == "fts_only"

    def test_freeze_is_idempotent(self):
        reg = ServiceRegistry()
        reg.freeze()
        reg.freeze()
        assert reg.is_frozen()

    def test_frozen_flag_not_in_as_dict(self):
        reg = ServiceRegistry()
        reg.freeze()
        d = reg.as_dict()
        assert "_frozen" not in d

    def test_parse_backends_valid_values(self):
        reg = ServiceRegistry()
        for valid in ("unstructured_api", "local_unstructured", "local_parsers"):
            reg.parse_backend = valid
            assert reg.parse_backend == valid

    def test_embed_backends_valid_values(self):
        reg = ServiceRegistry()
        for valid in ("ollama", "sentence_transformers"):
            reg.embed_backend = valid
            assert reg.embed_backend == valid

    def test_vector_backends_valid_values(self):
        reg = ServiceRegistry()
        for valid in ("qdrant", "chroma"):
            reg.vector_backend = valid
            assert reg.vector_backend == valid

    def test_module_singleton_exists(self):
        from app.core.registry import registry
        assert isinstance(registry, ServiceRegistry)
