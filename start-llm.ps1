#!/usr/bin/env pwsh
# Start script for kryten-llm service

$ErrorActionPreference = "Stop"

# Clear PYTHONPATH to avoid conflicts
$env:PYTHONPATH = ""

# Change to script directory
Set-Location $PSScriptRoot

# Start the service
uv run kryten-llm --config config.json
