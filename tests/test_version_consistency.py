import re
import pytest
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
PYPROJECT_PATH = ROOT_DIR / "pyproject.toml"
INIT_PATH = ROOT_DIR / "kryten_llm" / "__init__.py"

def get_pyproject_version():
    """Extract version from pyproject.toml."""
    content = PYPROJECT_PATH.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"(.*?)"', content, re.MULTILINE)
    assert match, "Could not find version in pyproject.toml"
    return match.group(1)

def get_init_version():
    """Extract version from __init__.py."""
    content = INIT_PATH.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\'](.*?)["\']', content, re.MULTILINE)
    assert match, "Could not find version in __init__.py"
    return match.group(1)

def test_version_consistency():
    """Ensure pyproject.toml and __init__.py versions match."""
    pyproject_ver = get_pyproject_version()
    init_ver = get_init_version()
    
    assert pyproject_ver == init_ver, \
        f"Version mismatch: pyproject.toml={pyproject_ver}, __init__.py={init_ver}"

def test_changelog_entry():
    """Ensure current version is in CHANGELOG.md."""
    pyproject_ver = get_pyproject_version()
    changelog_path = ROOT_DIR / "CHANGELOG.md"
    content = changelog_path.read_text(encoding="utf-8")
    
    assert f"[{pyproject_ver}]" in content, \
        f"Version {pyproject_ver} not found in CHANGELOG.md"
