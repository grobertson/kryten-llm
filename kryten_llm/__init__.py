"""Kryten LLM Service - Chat moderation and filtering."""

import os
from pathlib import Path


def _read_version() -> str:
    """Read version from VERSION file."""
    # Try package root first
    version_file = Path(__file__).parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()

    # Try repository root
    version_file = Path(__file__).parent.parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()

    return "0.0.0"


__version__ = _read_version()
