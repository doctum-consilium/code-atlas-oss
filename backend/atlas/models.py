"""Local search models: the embedder (vectors) and the reranker.

Both run on this machine (GPU if available); no text goes anywhere else. Deterministic fakes are
used by the tests and the CI, which have neither GPU nor downloaded model.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Any, Protocol


class Embedder(Protocol):
    """Turns text into a normalised vector of ``dimension`` components."""

    name: str
    dimension: int

    def documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Vectors of indexed chunks."""
        ...

    def query(self, question: str) -> list[float]:
        """Vector of a question (asymmetric models prefix it with an instruction)."""
        ...


class Reranker(Protocol):
    """Scores how relevant each chunk is to a question (higher is better)."""

    name: str

    def score(self, question: str, chunks: Sequence[str]) -> list[float]:
        """One score per chunk, in the given order."""
        ...


def _device() -> tuple[str, dict[str, Any]]:
    import torch

    if torch.cuda.is_available():
        return "cuda", {"torch_dtype": torch.float16}
    return "cpu", {}


class SentenceTransformerEmbedder:
    """Any sentence-transformers model; the default is ``Qwen/Qwen3-Embedding-0.6B``."""

    def __init__(
        self, name: str, dimension: int, query_prompt: str = "query", batch: int = 32
    ) -> None:
        self.name = name
        self.dimension = dimension
        self.query_prompt = query_prompt
        self.batch = batch
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            device, options = _device()
            self._model = SentenceTransformer(self.name, device=device, model_kwargs=options)
            self._model.max_seq_length = 1024
        return self._model

    def documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Batched, normalised vectors (cosine = dot product)."""
        vectors = self._load().encode(
            list(texts), batch_size=self.batch, normalize_embeddings=True, show_progress_bar=False
        )
        return self._check([[float(x) for x in v] for v in vectors])

    def query(self, question: str) -> list[float]:
        """Encode the question with the model's query prompt, if any."""
        options: dict[str, Any] = {"prompt_name": self.query_prompt} if self.query_prompt else {}
        vector = self._load().encode(
            [question], normalize_embeddings=True, show_progress_bar=False, **options
        )[0]
        return self._check([[float(x) for x in vector]])[0]

    def _check(self, vectors: list[list[float]]) -> list[list[float]]:
        if any(len(v) != self.dimension for v in vectors):
            raise RuntimeError(
                f"The embedder must produce exactly {self.dimension} dimensions "
                "([models] dimension in the settings)."
            )
        return vectors


class CrossEncoderReranker:
    """Any sentence-transformers cross-encoder; the default is ``BAAI/bge-reranker-v2-m3``."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._model: Any = None

    def score(self, question: str, chunks: Sequence[str]) -> list[float]:
        """Cross-encoder score for each (question, chunk) pair."""
        if not chunks:
            return []
        if self._model is None:
            from sentence_transformers import CrossEncoder

            device, options = _device()
            self._model = CrossEncoder(
                self.name, max_length=512, device=device, model_kwargs=options
            )
        scores = self._model.predict([(question, c) for c in chunks], show_progress_bar=False)
        return [float(s) for s in scores]


_WORD = re.compile(r"\w+")


class FakeEmbedder:
    """Deterministic double: bag of words hashed into ``dimension`` buckets, normalised.

    Texts sharing words get close vectors: enough to test semantic search without a model.
    """

    name = "fake-bag-of-words"

    def __init__(self, dimension: int = 1024) -> None:
        self.dimension = dimension

    def documents(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text."""
        return [self._vector(t) for t in texts]

    def query(self, question: str) -> list[float]:
        """Same transformation as documents."""
        return self._vector(question)

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for word in _WORD.findall(text.lower()):
            bucket = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=4).digest(), "big")
            vector[bucket % self.dimension] += 1.0
        if not any(vector):
            vector[0] = 1.0
        norm = math.sqrt(sum(x * x for x in vector))
        return [x / norm for x in vector]


class FakeReranker:
    """Deterministic double: share of the question's words found in the chunk."""

    name = "fake-overlap"

    def score(self, question: str, chunks: Sequence[str]) -> list[float]:
        """Score between 0 and 1 per chunk."""
        words = set(_WORD.findall(question.lower()))
        if not words:
            return [0.0 for _ in chunks]
        return [len(words & set(_WORD.findall(c.lower()))) / len(words) for c in chunks]
