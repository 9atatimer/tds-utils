"""EmbeddingPort contract, and the hashing fake that stands in for a model.

Design: Seams, "Embedding vendor and model | EmbeddingPort, model id at the
edge"; Data Model, "embedding: vector, with the model id that produced
it". Behaviors "A job is processed to an entry" and "An entry is placed"
(neighbours by embedding) need a deterministic, similarity-preserving
fake.
"""

import math
from collections.abc import Callable, Sequence

import pytest

from dynomark_daemon.ports.embedding import EmbeddingPort
from dynomark_daemon.testing.embedding import HashingEmbedding

pytestmark = pytest.mark.contract

EMBEDDINGS: dict[str, Callable[[], EmbeddingPort]] = {"hashing": HashingEmbedding}


@pytest.fixture(params=sorted(EMBEDDINGS))
def embedding(request: pytest.FixtureRequest) -> EmbeddingPort:
    return EMBEDDINGS[request.param]()


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.hypot(*a) * math.hypot(*b))


def test_embed_same_text_twice_gives_the_same_vector(embedding: EmbeddingPort) -> None:
    """Given one text, When embedded twice, Then the vectors are equal."""
    text = "Tokio is an asynchronous runtime for Rust"

    assert embedding.embed(text) == embedding.embed(text)


def test_embed_stamps_the_model_id_and_a_fixed_dimension(
    embedding: EmbeddingPort,
) -> None:
    """Given two texts, When embedded, Then both name the port's model id and
    have the same non-zero length (vectors are comparable)."""
    first = embedding.embed("rust async")
    second = embedding.embed("a much longer text about gardening and roses")

    assert first.model_id == second.model_id == embedding.model().model_id
    assert len(first.vector) == len(second.vector) > 0


def test_embed_non_empty_text_is_a_non_zero_vector(embedding: EmbeddingPort) -> None:
    """Given a non-empty text, When embedded, Then the vector is not all zeros
    (cosine similarity is defined)."""
    assert any(embedding.embed("bookmark").vector)


def test_hashing_embedding_ranks_shared_words_above_disjoint_ones() -> None:
    """Given texts sharing words and a text sharing none, When embedded, Then the
    sharing pair is more similar (neighbours by embedding are meaningful)."""
    fake = HashingEmbedding()
    anchor = fake.embed("rust async runtime tokio").vector
    near = fake.embed("tokio async runtime tutorial").vector
    far = fake.embed("sourdough bread baking").vector

    assert cosine(anchor, near) > cosine(anchor, far)


def test_hashing_embedding_is_case_insensitive() -> None:
    """Given one text in two cases, When embedded, Then the vectors are equal."""
    fake = HashingEmbedding()

    assert fake.embed("Rust Async").vector == fake.embed("rust async").vector
