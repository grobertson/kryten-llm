"""Kryten LLM Service - AI-powered chat responses for CyTube."""
import importlib.metadata

try:
    __version__ = importlib.metadata.version("kryten-llm")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

__author__ = "Kryten Robot Team"
__license__ = "MIT"
