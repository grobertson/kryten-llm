#!/bin/bash
# Start script for kryten-llm service

set -e

# Clear PYTHONPATH to avoid conflicts
export PYTHONPATH=""

# Change to script directory
cd "$(dirname "$0")"

# Activate virtual environment if it exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Start the service
poetry run kryten-llm --config config.json
