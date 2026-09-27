"""Smoke test against a real Ollama at $OLLAMA_HOST (default
http://127.0.0.1:11434) with the default models pulled. Skipped -- never
xfailed -- when Ollama is not reachable or a model is missing: the only
genuinely external dependency in this suite (task-025; tracked by
task-027, the laptop acceptance run).
"""

import os

import pytest

from dynomark_daemon.adapters.ollama import (
    OllamaClient,
    OllamaCompletion,
    OllamaEmbedding,
    OllamaError,
    has_model,
)
from dynomark_daemon.domain.config import ModelInfo
from dynomark_daemon.settings import DEFAULT_COMPLETION, DEFAULT_EMBEDDING, ollama_url
from tests._factories import make_bookmark, make_capture

pytestmark = pytest.mark.integration


def _live_client() -> OllamaClient:
    client = OllamaClient(ollama_url(os.environ), timeout_s=120.0)
    try:
        installed = client.installed_models()
    except OllamaError as error:
        pytest.skip(f"Ollama not reachable ({error}); see task-027")
    for name in (DEFAULT_EMBEDDING, DEFAULT_COMPLETION):
        if not has_model(installed, name):
            pytest.skip(f"model {name} is not pulled; see task-027")
    return client


def test_real_ollama_embeds_and_enriches() -> None:
    """Given a reachable Ollama with the default models, When a page is embedded
    and enriched, Then a non-zero vector and a non-empty summary come back."""
    client = _live_client()
    embedding = OllamaEmbedding(
        client,
        name=DEFAULT_EMBEDDING,
        model=ModelInfo(model_id=f"ollama:{DEFAULT_EMBEDDING}", local=True),
    )
    completion = OllamaCompletion(
        client,
        name=DEFAULT_COMPLETION,
        model=ModelInfo(model_id=f"ollama:{DEFAULT_COMPLETION}", local=True),
    )

    vector = embedding.embed("Tokio is an asynchronous runtime for Rust").vector
    enrichment = completion.enrich(
        make_bookmark(), make_capture("Tokio is an asynchronous runtime for Rust.")
    )

    assert any(vector) and enrichment.summary
