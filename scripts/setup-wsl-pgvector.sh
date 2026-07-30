#!/usr/bin/env bash
#
# Kryten memory DB — one-shot WSL setup (PostgreSQL 18 + pgvector).
#
# Run from the Windows repo checkout via WSL, e.g.:
#   wsl -d WLinux -- bash -lc "sudo bash /mnt/d/Devel/Kryten-Ecosystem/kryten-llm/scripts/setup-wsl-pgvector.sh"
#
# It is idempotent: safe to re-run. It installs PG 18 + pgvector, puts the
# cluster on localhost:5432 (reachable from Windows via WSL2 localhost
# forwarding), creates the `kryten` role + `kryten_memory` database, enables
# the `vector` extension, and writes the connection DSN (with a generated
# password) to ~/.kryten-memory.dsn (mode 600).
set -euo pipefail

PG_VER=18
CLUSTER=main
PORT=5432
DB=kryten_memory
ROLE=kryten

if [ "$(id -u)" -ne 0 ]; then
  echo "This script must run as root (use: sudo bash $0)" >&2
  exit 1
fi

TARGET_USER="${KRYTEN_TARGET_USER:-${SUDO_USER:-root}}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
DSN_FILE="$TARGET_HOME/.kryten-memory.dsn"

echo "[1/6] Installing PostgreSQL $PG_VER + pgvector ..."
export DEBIAN_FRONTEND=noninteractive
# Non-fatal: unrelated third-party repos (github-cli, pengwin) may have expired
# keys. The PostgreSQL repo is what matters and is cached; continue on warnings.
apt-get update -qq || echo "  (apt update reported warnings; continuing with cached indexes)"
apt-get install -y "postgresql-$PG_VER" "postgresql-$PG_VER-pgvector" openssl >/dev/null

echo "[2/6] Freeing port $PORT (stopping other clusters) ..."
# Stop every cluster except our target so PG 18/main can own $PORT.
while read -r ver clus _; do
  [ -z "${ver:-}" ] && continue
  if [ "$ver" != "$PG_VER" ] || [ "$clus" != "$CLUSTER" ]; then
    pg_ctlcluster "$ver" "$clus" stop >/dev/null 2>&1 || true
  fi
done < <(pg_lsclusters -h)

CONF_DIR="/etc/postgresql/$PG_VER/$CLUSTER"
if [ ! -d "$CONF_DIR" ]; then
  pg_createcluster "$PG_VER" "$CLUSTER" >/dev/null
fi

echo "[3/6] Configuring port + listen + pg_hba ..."
pg_ctlcluster "$PG_VER" "$CLUSTER" stop >/dev/null 2>&1 || true
sed -i "s/^#\?\s*port\s*=.*/port = $PORT/" "$CONF_DIR/postgresql.conf"
sed -i "s/^#\?\s*listen_addresses\s*=.*/listen_addresses = '*'/" "$CONF_DIR/postgresql.conf"

HBA="$CONF_DIR/pg_hba.conf"
if ! grep -q "kryten-memory" "$HBA"; then
  {
    echo ""
    echo "# kryten-memory: password auth from the Windows host over WSL2."
    echo "# WSL2's virtual network is host-local (not LAN-routable); scram-sha-256"
    echo "# still requires the role password. Tighten the CIDR if you prefer."
    echo "host    all    all    0.0.0.0/0    scram-sha-256"
    echo "host    all    all    ::/0         scram-sha-256"
  } >> "$HBA"
fi

echo "[4/6] Starting cluster ..."
pg_ctlcluster "$PG_VER" "$CLUSTER" start

echo "[5/6] Creating role + database + extension ..."
PW="$(openssl rand -hex 20)"
if sudo -u postgres psql -p "$PORT" -tAc "SELECT 1 FROM pg_roles WHERE rolname='$ROLE'" | grep -q 1; then
  sudo -u postgres psql -p "$PORT" -c "ALTER ROLE $ROLE LOGIN PASSWORD '$PW';" >/dev/null
else
  sudo -u postgres psql -p "$PORT" -c "CREATE ROLE $ROLE LOGIN PASSWORD '$PW';" >/dev/null
fi

if ! sudo -u postgres psql -p "$PORT" -tAc "SELECT 1 FROM pg_database WHERE datname='$DB'" | grep -q 1; then
  sudo -u postgres createdb -p "$PORT" -O "$ROLE" "$DB"
fi

sudo -u postgres psql -v ON_ERROR_STOP=1 -p "$PORT" -d "$DB" >/dev/null <<SQL
CREATE EXTENSION IF NOT EXISTS vector;
GRANT ALL ON SCHEMA public TO $ROLE;
SQL

echo "[6/6] Writing DSN file ($DSN_FILE) ..."
printf 'postgresql://%s:%s@localhost:%s/%s\n' "$ROLE" "$PW" "$PORT" "$DB" > "$DSN_FILE"
chown "$TARGET_USER" "$DSN_FILE"
chmod 600 "$DSN_FILE"

echo "KRYTEN_SETUP_OK pg=$PG_VER port=$PORT db=$DB role=$ROLE dsn_file=$DSN_FILE"
