$ErrorActionPreference = "Stop"

# Get the directory of this script
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$pyprojectPath = Join-Path $scriptDir ".." "pyproject.toml"

# Check if pyproject.toml exists
if (-not (Test-Path $pyprojectPath)) {
    Write-Host "Error: pyproject.toml not found at $pyprojectPath" -ForegroundColor Red
    exit 1
}

# Read version from pyproject.toml
$content = Get-Content $pyprojectPath -Raw
if ($content -match 'version = "(\d+\.\d+\.\d+)"') {
    $version = $matches[1]
} else {
    Write-Host "Error: Version not found in pyproject.toml" -ForegroundColor Red
    exit 1
}

Write-Host $version

# Git commands
git add .
# Note: Added message format to make it valid, original was empty
git commit -m "Release v$version"
git push origin main
git tag "v$version"
git push origin "v$version"
