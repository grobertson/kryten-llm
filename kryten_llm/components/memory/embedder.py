"""Embedder interface and backend implementations.

Phase 7b / 7e: REQ-020 through REQ-023.

Backends
--------
* ``onnx`` — In-process ONNX model (default; no network, no API key).
             Requires the ``[memory]`` optional extra.
* ``openai_compatible`` — HTTP client against any OpenAI-compatible endpoint
                          (LM Studio, Ollama, vLLM, OpenAI, etc.).
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

#: Registry: config ``type`` → embedder class.
EMBEDDER_REGISTRY: dict[str, type] = {}


def _register_embedder(type_key: str):
    def _dec(cls):
        EMBEDDER_REGISTRY[type_key] = cls
        return cls

    return _dec


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Embedder(Protocol):
    """Interface all embedding backends must satisfy.

    REQ-020: ``embed(texts) -> list[vector]``, plus ``dimension`` and ``id``.
    """

    id: str
    dimension: int

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of *texts* and return a parallel list of vectors."""
        ...


# ---------------------------------------------------------------------------
# ONNX backend (in-process, default)
# ---------------------------------------------------------------------------


@_register_embedder("onnx")
class OnnxEmbedder:
    """In-process ONNX embedding backend.

    Requires ``kryten-llm[memory]`` (``sentence-transformers`` +
    ``onnxruntime``).  Uses ``all-MiniLM-L6-v2`` by default (384-dim).

    REQ-021 / CON-005: Heavy deps are optional.
    """

    id = "onnx"

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None  # Lazy-loaded
        self._dimension: int | None = None

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "OnnxEmbedder":
        return cls(model_name=cfg.get("model", "all-MiniLM-L6-v2"))

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._ensure_loaded()
        return self._dimension or 384  # fallback

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

            self._model = SentenceTransformer(self._model_name)
            test_vec = self._model.encode(["test"])
            self._dimension = int(test_vec.shape[1])
            logger.info(
                f"OnnxEmbedder loaded '{self._model_name}' (dim={self._dimension})"
            )
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is required for the ONNX embedder. "
                "Install it with: pip install 'kryten-llm[memory]'"
            ) from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Encode *texts* synchronously (ONNX is CPU-bound).

        REQ-023: Embedding calls must be batched and not on the critical path;
        the caller is responsible for scheduling off-path.
        """
        self._ensure_loaded()
        if not texts:
            return []
        vectors = self._model.encode(texts, convert_to_numpy=True)
        return [v.tolist() for v in vectors]


# ---------------------------------------------------------------------------
# OpenAI-compatible HTTP backend
# ---------------------------------------------------------------------------


@_register_embedder("openai_compatible")
class OpenAICompatibleEmbedder:
    """HTTP embedder for OpenAI-compatible endpoints.

    Supports LM Studio, Ollama, vLLM, and the real OpenAI API.

    REQ-021: ``type: openai_compatible``.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        dimension: int = 384,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._dimension = dimension
        self._resolved_dimension: int | None = None

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "OpenAICompatibleEmbedder":
        return cls(
            base_url=cfg["base_url"],
            model=cfg["model"],
            api_key=cfg.get("api_key", ""),
            dimension=cfg.get("dimension", 384),
        )

    @property
    def id(self) -> str:
        return f"openai_compatible:{self._model}"

    @property
    def dimension(self) -> int:
        return self._resolved_dimension or self._dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        try:
            import aiohttp  # already a project dependency

            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = "Bearer " + self._api_key

            payload = {"input": texts, "model": self._model}
            url = f"{self._base_url}/embeddings"

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    resp.raise_for_status()
                    data = await resp.json()

            vectors = [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]

            if vectors and self._resolved_dimension is None:
                self._resolved_dimension = len(vectors[0])

            return vectors

        except Exception as exc:
            logger.error(f"OpenAICompatibleEmbedder.embed() failed: {exc}", exc_info=True)
            raise


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_embedder(cfg: dict[str, Any]) -> Embedder:
    """Instantiate an embedder from a config dict.

    REQ-021: Selects backend by ``cfg["type"]``.
    """
    etype = cfg.get("type", "onnx")
    cls = EMBEDDER_REGISTRY.get(etype)
    if cls is None:
        raise ValueError(f"Unknown embedder type '{etype}'. Known: {list(EMBEDDER_REGISTRY)}")
    return cls.from_config(cfg)
