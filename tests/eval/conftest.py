"""Shared pytest fixtures for the eval suite (Sprint 12, Sortie 1, REQ-252–254)."""

from __future__ import annotations

import pytest

from tests.eval.harness import FakeEmbedder, FakeStore


@pytest.fixture()
def fake_embedder() -> FakeEmbedder:
    """Deterministic keyword-based embedder; no ONNX required."""
    return FakeEmbedder()


@pytest.fixture()
def fake_store() -> FakeStore:
    """Fresh in-memory store for each test."""
    return FakeStore()
