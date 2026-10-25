"""Embedding providers.

A provider is any object with ``model_id``, ``dimension``, ``sends_data_externally`` and
``embed(texts) -> ndarray[(n, dimension), float32]``. Two are built in:

* :class:`SentenceTransformerEmbedding` — a local ``sentence-transformers`` model
  (``pip install relvector[local]``). Nothing leaves the machine; the model is downloaded by
  sentence-transformers on first use unless ``local_files_only=True``.
* :class:`HashingEmbedding` — dependency-free, deterministic lexical feature hashing. It is not a
  semantic model; it exists for tests, offline demos and as a keyword-ish baseline.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from relvector.errors import RelVectorError

Vectors = NDArray[np.float32]


@runtime_checkable
class EmbeddingProvider(Protocol):
    model_id: str
    sends_data_externally: bool

    @property
    def dimension(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> Vectors: ...


def normalize(vectors: Any) -> Vectors:
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim != 2:
        raise RelVectorError(f"embeddings must be 2-dimensional, got shape {arr.shape}")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    out: Vectors = arr / norms
    return out


_TOKEN = re.compile(r"[a-z0-9]+")


class HashingEmbedding:
    """Signed feature hashing of words and character trigrams (stable across processes)."""

    sends_data_externally = False

    def __init__(self, dimension: int = 512) -> None:
        if dimension < 8:
            raise ValueError("dimension must be >= 8")
        self._dimension = dimension
        self.model_id = f"hashing-v1-{dimension}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def _features(self, text: str) -> list[str]:
        feats: list[str] = []
        for word in _TOKEN.findall(text.lower()):
            feats.append(f"w:{word}")
            padded = f"#{word}#"
            feats.extend(f"c:{padded[i:i + 3]}" for i in range(len(padded) - 2))
        return feats

    def embed(self, texts: Sequence[str]) -> Vectors:
        out = np.zeros((len(texts), self._dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            for feat in self._features(text):
                h = int.from_bytes(hashlib.blake2b(feat.encode(), digest_size=8).digest(), "little")
                out[row, h % self._dimension] += 1.0 if (h >> 63) & 1 else -1.0
        return normalize(out)


class SentenceTransformerEmbedding:
    """A local sentence-transformers model, loaded lazily on first use."""

    sends_data_externally = False

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        *,
        device: str | None = None,
        batch_size: int = 64,
        local_files_only: bool = False,
    ) -> None:
        self.model_name = model_name
        self.model_id = f"sentence-transformers:{model_name}"
        self.device = device
        self.batch_size = batch_size
        self.local_files_only = local_files_only
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer  # noqa: PLC0415
            except ImportError as exc:  # pragma: no cover - depends on the environment
                raise RelVectorError(
                    f"the 'local' embedding provider could not import sentence-transformers "
                    f"({exc}); pip install 'relvector[local]' or use "
                    "embedding_provider='hashing'"
                ) from exc
            self._model = SentenceTransformer(
                self.model_name, device=self.device, local_files_only=self.local_files_only
            )
        return self._model

    @property
    def dimension(self) -> int:
        dim = self._load().get_sentence_embedding_dimension()
        if not dim:
            raise RelVectorError(f"model {self.model_name!r} does not report a dimension")
        return int(dim)

    def embed(self, texts: Sequence[str]) -> Vectors:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        vectors = self._load().encode(
            list(texts), batch_size=self.batch_size, convert_to_numpy=True,
            normalize_embeddings=True, show_progress_bar=False,
        )
        return normalize(vectors)


def get_provider(spec: str | EmbeddingProvider, **kwargs: Any) -> EmbeddingProvider:
    """Resolve ``"local"``/``"sentence-transformers"``, ``"hashing"`` or a provider instance."""
    if not isinstance(spec, str):
        if not isinstance(spec, EmbeddingProvider):
            raise RelVectorError("embedding_provider must be a name or an EmbeddingProvider")
        return spec
    if spec in ("local", "sentence-transformers"):
        return SentenceTransformerEmbedding(**kwargs)
    if spec == "hashing":
        return HashingEmbedding(**kwargs)
    raise RelVectorError(f"unknown embedding provider {spec!r}; use 'local' or 'hashing'")
