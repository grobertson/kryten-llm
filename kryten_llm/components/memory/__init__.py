"""Long-term memory subsystem for kryten-llm.

Phase 7b: Embedder, VectorStore, FactExtractor interfaces and implementations.
"""

from kryten_llm.components.memory.embedder import (
    EMBEDDER_REGISTRY,
    Embedder,
    OnnxEmbedder,
    OpenAICompatibleEmbedder,
)
from kryten_llm.components.memory.extractor import (
    EXTRACTOR_REGISTRY,
    ExtractedFact,
    Fact,
    FactExtractor,
    register_extractor,
)
from kryten_llm.components.memory.heuristic_extractor import HeuristicFactExtractor
from kryten_llm.components.memory.llm_extractor import LLMFactExtractor
from kryten_llm.components.memory.safety import is_safe_message
from kryten_llm.components.memory.vector_store import (
    VECTOR_STORE_REGISTRY,
    VectorStore,
)

__all__ = [
    "Embedder",
    "OnnxEmbedder",
    "OpenAICompatibleEmbedder",
    "EMBEDDER_REGISTRY",
    "VectorStore",
    "VECTOR_STORE_REGISTRY",
    "ExtractedFact",
    "Fact",
    "FactExtractor",
    "EXTRACTOR_REGISTRY",
    "register_extractor",
    "HeuristicFactExtractor",
    "LLMFactExtractor",
    "is_safe_message",
]
