#!/bin/bash
# Start script for kryten-llm service

set -e

# Clear PYTHONPATH to avoid conflicts
export PYTHONPATH=""

# Change to script directory
cd "$(dirname "$0")"

# Start the service
uv run kryten-llm --config config.json
