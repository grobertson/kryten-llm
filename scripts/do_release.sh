#!/bin/bash

# Read version from ..\pyproject.toml
VERSION=$(grep -oP 'version = "\K[0-9]+\.[0-9]+\.[0-9]+' ../pyproject.toml)

# Check if version is empty
if [ -z "$VERSION" ]; then
    echo "Error: Version not found in pyproject.toml"
    exit 1
fi

echo $VERSION


git add .
git commit -m ""
git push origin main
git tag v$VERSION
git push origin v$VERSION