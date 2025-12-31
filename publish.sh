#!/bin/bash
# Kryten-LLM PyPI Publishing Script
# Version: 1.0.0 (Standardized UV)

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Flags
BUILD=false
PUBLISH=false
TESTPYPI=false
CLEAN=false
HELP=false

function print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

function print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

function show_help() {
    cat <<EOF
Usage: ./publish.sh [OPTIONS]

Options:
    --clean      Clean build artifacts
    --build      Build the package (uv build)
    --testpypi   Publish to TestPyPI
    --publish    Publish to production PyPI
    --help       Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --build) BUILD=true; shift ;;
        --publish) PUBLISH=true; shift ;;
        --testpypi) TESTPYPI=true; shift ;;
        --clean) CLEAN=true; shift ;;
        --help) HELP=true; shift ;;
        *) print_error "Unknown option: $1"; show_help; exit 1 ;;
    esac
done

if [ "$HELP" = true ]; then
    show_help
    exit 0
fi

# Read version from pyproject.toml
if [ -f "pyproject.toml" ]; then
    VERSION=$(grep -m1 'version = "' pyproject.toml | cut -d '"' -f 2)
    print_info "Package version: $VERSION"
else
    print_error "pyproject.toml not found"
    exit 1
fi

if [ "$CLEAN" = true ]; then
    print_info "Cleaning build artifacts..."
    rm -rf dist/ build/ *.egg-info/
fi

if [ "$BUILD" = true ]; then
    print_info "Building package with uv..."
    uv build
fi

if [ "$TESTPYPI" = true ]; then
    print_info "Publishing to TestPyPI..."
    uv publish --repository testpypi
fi

if [ "$PUBLISH" = true ]; then
    print_info "Publishing to PyPI..."
    uv publish
fi
