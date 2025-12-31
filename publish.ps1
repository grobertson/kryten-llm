# Kryten-LLM PyPI Publishing Script
# Version: 1.0.0 (Standardized UV)

param (
    [switch]$Clean,
    [switch]$Build,
    [switch]$Publish,
    [switch]$TestPyPI,
    [switch]$Help
)

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Green
}

function Write-ErrorMsg {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

if ($Help) {
    Write-Host "Usage: .\publish.ps1 [OPTIONS]"
    Write-Host "Options:"
    Write-Host "    -Clean      Clean build artifacts"
    Write-Host "    -Build      Build the package (uv build)"
    Write-Host "    -TestPyPI   Publish to TestPyPI"
    Write-Host "    -Publish    Publish to production PyPI"
    exit
}

# Read version from pyproject.toml
if (Test-Path "pyproject.toml") {
    $VersionLine = Select-String -Path "pyproject.toml" -Pattern 'version = "(.*)"'
    if ($VersionLine) {
        $Version = $VersionLine.Matches.Groups[1].Value
        Write-Info "Package version: $Version"
    } else {
        Write-ErrorMsg "Version not found in pyproject.toml"
        exit 1
    }
} else {
    Write-ErrorMsg "pyproject.toml not found"
    exit 1
}

if ($Clean) {
    Write-Info "Cleaning build artifacts..."
    if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
    if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
    Get-ChildItem -Path . -Filter "*.egg-info" -Recurse | Remove-Item -Recurse -Force
}

if ($Build) {
    Write-Info "Building package with uv..."
    uv build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if ($TestPyPI) {
    Write-Info "Publishing to TestPyPI..."
    uv publish --repository testpypi
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if ($Publish) {
    Write-Info "Publishing to PyPI..."
    uv publish
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
