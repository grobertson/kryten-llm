#!/usr/bin/env python3
"""
Version Management Script for Kryten LLM.

Usage:
    python scripts/manage_version.py sync
    python scripts/manage_version.py verify
    python scripts/manage_version.py release
"""

import re
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# Paths
ROOT_DIR = Path(__file__).parent.parent
PYPROJECT_PATH = ROOT_DIR / "pyproject.toml"
INIT_PATH = ROOT_DIR / "kryten_llm" / "__init__.py"
CHANGELOG_PATH = ROOT_DIR / "CHANGELOG.md"

def get_pyproject_version():
    """Extract version from pyproject.toml."""
    content = PYPROJECT_PATH.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"(.*?)"', content, re.MULTILINE)
    if not match:
        print("Error: Could not find version in pyproject.toml")
        sys.exit(1)
    return match.group(1)

def update_init_file(version):
    """Update version in __init__.py."""
    content = INIT_PATH.read_text(encoding="utf-8")
    
    # Regex to replace __version__ = "..."
    # Handles both single and double quotes
    pattern = r'^__version__\s*=\s*["\'].*?["\']'
    replacement = f'__version__ = "{version}"'
    
    new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    
    if content != new_content:
        INIT_PATH.write_text(new_content, encoding="utf-8")
        print(f"Updated {INIT_PATH.name} to version {version}")
    else:
        print(f"{INIT_PATH.name} is already up to date")

def check_changelog(version):
    """Check if version exists in CHANGELOG.md."""
    content = CHANGELOG_PATH.read_text(encoding="utf-8")
    
    # Check for [version] header
    if f"[{version}]" not in content:
        print(f"Warning: Version {version} not found in CHANGELOG.md")
        return False
    
    print(f"Found version {version} in CHANGELOG.md")
    return True

def verify_consistency():
    """Verify all version numbers match."""
    pyproject_ver = get_pyproject_version()
    
    # Check __init__.py
    init_content = INIT_PATH.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\'](.*?)["\']', init_content, re.MULTILINE)
    if not match:
        print(f"Error: Could not find version in {INIT_PATH.name}")
        return False
        
    init_ver = match.group(1)
    
    if pyproject_ver != init_ver:
        print(f"Error: Version mismatch! pyproject.toml: {pyproject_ver}, __init__.py: {init_ver}")
        return False
        
    print(f"Version consistency check passed: {pyproject_ver}")
    return True

def run_tests():
    """Run verification tests."""
    print("Running tests...")
    result = subprocess.run(["pytest", "tests/test_version_consistency.py"], capture_output=True, text=True)
    if result.returncode != 0:
        print("Tests failed!")
        print(result.stdout)
        print(result.stderr)
        return False
    print("Tests passed.")
    return True

def sync():
    """Sync version from pyproject.toml to other files."""
    version = get_pyproject_version()
    print(f"Syncing version {version}...")
    update_init_file(version)
    check_changelog(version)

def release():
    """Prepare for release."""
    print("Preparing release...")
    version = get_pyproject_version()
    
    # 1. Sync files
    sync()
    
    # 2. Verify consistency
    if not verify_consistency():
        sys.exit(1)
        
    # 3. Check changelog
    if not check_changelog(version):
        print("Please update CHANGELOG.md before releasing.")
        # Don't exit, just warn? Or exit?
        # sys.exit(1)
        
    # 4. Run tests (including new version consistency test)
    if not run_tests():
        sys.exit(1)
        
    print(f"\nRelease preparation for {version} complete!")
    print("Next steps:")
    print(f"  git commit -am 'chore: bump version to {version}'")
    print(f"  git tag v{version}")
    print("  git push origin main --tags")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
        
    command = sys.argv[1]
    
    if command == "sync":
        sync()
    elif command == "verify":
        if not verify_consistency():
            sys.exit(1)
    elif command == "release":
        release()
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)

if __name__ == "__main__":
    main()
