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
            """Yield deterministic non-zero vectors so FAISS scoring is stable."""
            for text in texts:
                seed = abs(hash(text) + 42) % (2 ** 31)
                rng = np.random.default_rng(seed)
                yield rng.standard_normal(384).astype("float32")

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
