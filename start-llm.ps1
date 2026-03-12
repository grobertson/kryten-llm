#!/usr/bin/env pwsh
# Start script for kryten-llm service

$ErrorActionPreference = "Stop"

function Test-VenvValid {
	param([string]$Path)

	if (-not (Test-Path $Path)) { return $false }

	$pythonExe = Join-Path $Path "Scripts\python.exe"
	$pipExe = Join-Path $Path "Scripts\pip.exe"
	$pyvenvCfg = Join-Path $Path "pyvenv.cfg"

	if (-not (Test-Path $pyvenvCfg)) { return $false }
	if (-not (Test-Path $pythonExe) -or -not (Test-Path $pipExe)) { return $false }

	try {
		& $pythonExe -c "import sys" *> $null
		return $true
	} catch {
		return $false
	}
}

function New-VirtualEnvironment {
	param([string]$Path)

	$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
	if ($uvCmd) {
		& uv venv $Path
	} else {
		& python -m venv $Path
	}
}

# Clear PYTHONPATH to avoid conflicts
$env:PYTHONPATH = ""

# Change to script directory
Set-Location $PSScriptRoot

# Ensure .venv is usable; recreate it if pyvenv metadata is missing/corrupted.
$venvPath = Join-Path $PSScriptRoot ".venv"
if (-not (Test-VenvValid -Path $venvPath)) {
	if (Test-Path $venvPath) {
		try {
			Remove-Item -Recurse -Force $venvPath -ErrorAction Stop
		} catch {
			throw "Could not remove corrupted .venv at $venvPath. Close terminals/processes using this environment and try again."
		}
	}
	New-VirtualEnvironment -Path $venvPath

	if (-not (Test-VenvValid -Path $venvPath)) {
		throw "Failed to create a valid virtual environment at $venvPath"
	}
}

# Start the service
uv run kryten-llm --config config.json --log-level DEBUG
