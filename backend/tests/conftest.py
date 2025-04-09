"""Shared pytest fixtures and configuration."""
import sys
import types
import numpy as np
import pytest


# ── Mock fastembed se não instalado (CI / ambientes leves) ───────────────────

def _ensure_fastembed_mock():
    if "fastembed" in sys.modules:
        return

    mock_fe = types.ModuleType("fastembed")

    class _MockTextEmbedding:
        def __init__(self, model_name: str = "", **kw):
            self.model_name = model_name

        def embed(self, texts):
            """Yield zero-vectors with the correct dimension (384)."""
            for _ in texts:
                yield np.zeros(384, dtype="float32")

    mock_fe.TextEmbedding = _MockTextEmbedding
    sys.modules["fastembed"] = mock_fe


_ensure_fastembed_mock()


@pytest.fixture(autouse=True)
def reset_rag_singletons():
    """Reset in-memory FAISS singletons between tests to avoid state leakage."""
    import app.services.rag as rag_module
    rag_module._model = None
    rag_module._index = None
    rag_module._meta = None
    yield
    rag_module._model = None
    rag_module._index = None
    rag_module._meta = None
