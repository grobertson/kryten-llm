# Ensure the Kryten memory database (PG17 + pgvector in the kryten-pg WSL distro)
# is running and reachable from Windows. Idempotent — run before the service or
# a `memory seed` job, especially after a Windows reboot (which stops the distro).
#
#   ./scripts/start-memory-db.ps1
$ErrorActionPreference = "Stop"

Write-Host "Starting Postgres in the kryten-pg distro ..."
wsl -d kryten-pg -u root /usr/local/bin/start-kryten-pg.sh | Out-Null

# Verify reachability from Windows using the configured DSN.
# Make sure the DSN is in this process env for the reachability check.
if (-not $env:KRYTEN_MEMORY_DSN) {
    $env:KRYTEN_MEMORY_DSN = [Environment]::GetEnvironmentVariable("KRYTEN_MEMORY_DSN", "User")
}
if (-not $env:KRYTEN_MEMORY_DSN) {
    Write-Warning "KRYTEN_MEMORY_DSN is not set; cannot verify. See docs/wsl-alpine-pgvector-setup.md."
    exit 1
}

$py = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
& $py -c "import asyncio,asyncpg,os; asyncio.run(asyncpg.connect(os.environ['KRYTEN_MEMORY_DSN'])); print('Kryten memory DB is up and reachable.')"
