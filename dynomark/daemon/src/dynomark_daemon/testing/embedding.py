"""A deterministic hashing ``EmbeddingPort``: feature hashing of words.

Each lower-cased word adds +/-1 to one of ``dimensions`` buckets chosen by
SHA-256, then the vector is L2-normalized; a text with no words maps to
the first basis vector so cosine similarity is always defined. Texts
sharing words land close; no model, no network, identical on every run.
"""

import hashlib
import math
import re
from typing import Final

from dynomark_daemon.domain.bookmark import Embedding
from dynomark_daemon.domain.config import ModelInfo

WORD: Final = re.compile(r"\w+")


def _bucket_and_sign(word: str, dimensions: int) -> tuple[int, float]:
    digest = hashlib.sha256(word.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") % dimensions
    return bucket, 1.0 if digest[8] & 1 else -1.0


class HashingEmbedding:
    def __init__(self, *, dimensions: int = 64, model_id: str = "fake:hashing") -> None:
        self._dimensions = dimensions
        self._model = ModelInfo(model_id=model_id, local=True)

    def model(self) -> ModelInfo:
        return self._model

    def embed(self, text: str) -> Embedding:
        vector = [0.0] * self._dimensions
        for word in WORD.findall(text.lower()):
            bucket, sign = _bucket_and_sign(word, self._dimensions)
            vector[bucket] += sign
        norm = math.hypot(*vector)
        if norm == 0.0:
            vector[0] = 1.0
            norm = 1.0
        return Embedding(
            vector=tuple(x / norm for x in vector), model_id=self._model.model_id
        )
