"""Seam: the embedding vendor and model (model id at the edge)."""

from typing import Protocol

from dynomark_daemon.domain.bookmark import Embedding
from dynomark_daemon.domain.config import ModelInfo
from dynomark_daemon.ports.errors import PortError


class EmbeddingError(PortError):
    """The embedding call failed."""


class EmbeddingPort(Protocol):
    def model(self) -> ModelInfo:
        """The model this port embeds with."""
        ...

    def embed(self, text: str) -> Embedding:
        """Embed ``text``; the result names ``model().model_id``.

        Raises:
            EmbeddingError: the model could not embed it.
        """
        ...
