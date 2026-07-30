# Kryten memory DB — WSL Alpine + pgvector (local Windows setup)

This documents the **local** Postgres-for-memory setup used on this machine: a
dedicated, isolated **Alpine WSL2 distro** (`kryten-pg`) running **PostgreSQL 17
+ pgvector**, reachable from Windows at `localhost:5432`. It's the concurrency-
safe backend for `kryten-llm`'s long-term memory (the embedded Chroma client is
single-process and corrupts under concurrent writes).

Why a dedicated Alpine distro:

- **Isolation** — a throwaway distro, separate from anything else (and from the
  Django CMS Postgres). Blowing it away is `wsl --unregister kryten-pg`.
- **Clean packages** — Alpine's `apk` has `pgvector` in its community repo as a
  one-line install. (The pre-existing Debian-based `WLinux` distro had drifted
  into a mixed-sources "Frankendebian" state where installing Postgres wanted a
  destructive partial dist-upgrade — avoided entirely here.)
- **No native Windows build** — pgvector isn't packaged for native Windows PG
  and would require building from source with MSVC.

Final facts: distro `kryten-pg` · PostgreSQL 17 · database `kryten_memory` ·
role `kryten` · port `5432` · DSN file `/root/.kryten-memory.dsn`.

---

## Prerequisites

- WSL2 (this machine: WSL 2.6.3).
- **Port 5432 free on Windows.** Any native Windows Postgres must be stopped —
  it will otherwise hijack `localhost:5432` and cause `password authentication
  failed` (Windows silently connects to the *wrong* Postgres). Stop/disable the
  `postgresql-x64-*` service.

## Setup (reproducible)

### 1. Import a dedicated Alpine distro

```powershell
# Download the current Alpine minirootfs (x86_64)
$tar = "$env:TEMP\alpine-minirootfs-3.21.7-x86_64.tar.gz"
Invoke-WebRequest -UseBasicParsing `
  "https://dl-cdn.alpinelinux.org/alpine/v3.21/releases/x86_64/alpine-minirootfs-3.21.7-x86_64.tar.gz" `
  -OutFile $tar
New-Item -ItemType Directory -Force D:\wsl\kryten-pg | Out-Null
wsl --import kryten-pg D:\wsl\kryten-pg $tar --version 2
```

### 2. Install + configure Postgres + pgvector

Run the setup script (idempotent) as root inside the new distro. It installs
PG 17 + `postgresql-pgvector`, initialises a cluster on `localhost:5432`,
creates the `kryten` role + `kryten_memory` DB with a generated password,
enables the `vector` extension, starts Postgres, and writes the DSN to
`/root/.kryten-memory.dsn`:

```powershell
wsl -d kryten-pg -u root -- sh -c "tr -d '\r' < /mnt/d/Devel/Kryten-Ecosystem/kryten-llm/scripts/setup-alpine-pgvector.sh > /tmp/setup.sh; sh /tmp/setup.sh"
```

Script: [../scripts/setup-alpine-pgvector.sh](../scripts/setup-alpine-pgvector.sh).

> WSL runs `-u root` without a password (the distro owner is root-capable), so
> no sudo/secret handling is needed.

### 3. Expose the DSN to Windows

The generated password lives only in `/root/.kryten-memory.dsn`. Copy it into a
Windows user env var (`config.json` reads it via `dsn_env`) without printing it:

```powershell
$dsn = (wsl -d kryten-pg -u root -- cat /root/.kryten-memory.dsn | Out-String).Trim()
$env:KRYTEN_MEMORY_DSN = $dsn        # current session
setx KRYTEN_MEMORY_DSN "$dsn" | Out-Null   # persist for future sessions
```

### 4. Point kryten-llm at it

`config.json` → `context.providers[long_term_memory].store`:

```json
"store": {
  "backend": "pgvector",
  "dsn_env": "KRYTEN_MEMORY_DSN",
  "table": "user_facts",
  "pool_min_size": 1,
  "pool_max_size": 8
}
```

Install the extra once: `uv sync --extra memory --extra pgvector`. The
`user_facts` table is auto-created on first run (schema:
[../sql/002_user_facts.sql](../sql/002_user_facts.sql)).

## Auto-start on boot

WSL distros have no init; Postgres is started by `/etc/wsl.conf`'s `[boot]`
command, which runs [/usr/local/bin/start-kryten-pg.sh](../scripts/start-kryten-pg.sh).
That script recreates the socket dir (`/run` is a tmpfs wiped on every restart)
and starts Postgres via the **versioned** binary
`/usr/libexec/postgresql17/pg_ctl` (the `/usr/bin/pg_ctl` wrapper isn't
resolvable in the minimal boot environment).

The `[boot]` command only fires when the distro is launched. To bring it up
after a Windows reboot, either open the distro once, or add a **logon scheduled
task** (run once, elevated):

```powershell
# Run in an ADMIN PowerShell
$a = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d kryten-pg -u root /usr/local/bin/start-kryten-pg.sh"
$t = New-ScheduledTaskTrigger -AtLogOn
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "Kryten-PG-Autostart" -Action $a -Trigger $t -Settings $s -Force
```

## Everyday commands

```powershell
# Ensure the DB is up + reachable (idempotent) — run this before the service or
# a `memory seed` job, especially after a Windows reboot.
./scripts/start-memory-db.ps1

# Start / status (start is idempotent)
wsl -d kryten-pg -u root /usr/local/bin/start-kryten-pg.sh
wsl -d kryten-pg -u root -- su postgres -c "/usr/libexec/postgresql17/pg_ctl -D /var/lib/postgresql/17/data status"

# psql shell
wsl -d kryten-pg -u root -- su postgres -c "psql -p 5432 -d kryten_memory"

# Backup / restore
wsl -d kryten-pg -u root -- su postgres -c "pg_dump -p 5432 kryten_memory" > backup.sql

# Stop everything (all distros) / remove this distro entirely
wsl --shutdown
wsl --unregister kryten-pg
```

## Troubleshooting

- **`password authentication failed for user "kryten"`** — Windows is connecting
  to a *different* Postgres on 5432 (usually a leftover native Windows PG). Stop
  it, then `wsl --shutdown` and relaunch the distro.
- **`connection refused` from Windows** — the WSL `localhost:5432` relay wasn't
  established (e.g. the port was occupied when the distro's PG started). Fix:
  `wsl --shutdown`, ensure nothing else holds 5432, relaunch the distro.
- **PG didn't start on boot** — check `/var/log/kryten-pg-boot.log` and
  `/var/log/postgresql.log` inside the distro. A missing `/run/postgresql` or a
  bare `pg_ctl` (wrapper) are the usual causes; the current start script handles
  both.
- **`Error loading hnsw index` (old Chroma data)** — unrelated to pgvector; that
  was the corrupted embedded Chroma store. pgvector replaces it.

## Notes

- Per-user fact sets are small (cap ~350), so exact cosine search under the
  `username` btree is fast; no ANN index is needed.
- WSL2's virtual network is host-local (not LAN-routable). `pg_hba.conf` still
  requires the role password (scram-sha-256); tighten the CIDR if you prefer.
- General backend reference (config options, migration): [pgvector-setup.md](pgvector-setup.md).
