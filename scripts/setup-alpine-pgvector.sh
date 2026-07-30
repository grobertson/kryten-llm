#!/bin/sh
#
# Kryten memory DB — setup for a dedicated Alpine WSL distro (PostgreSQL 17 +
# pgvector). Alpine's `apk` is clean, so this avoids the mixed-sources
# ("Frankendebian") breakage seen on the Debian-based WLinux distro.
#
# Run as root inside the dedicated distro, e.g.:
#   wsl -d kryten-pg -u root -- sh /mnt/d/Devel/Kryten-Ecosystem/kryten-llm/scripts/setup-alpine-pgvector.sh
#
# Idempotent: safe to re-run. Installs PG17 + pgvector, initialises a cluster
# on localhost:5432 (reachable from Windows via WSL2 localhost forwarding),
# creates the `kryten` role + `kryten_memory` DB, enables the `vector`
# extension, starts Postgres, and writes the connection DSN (with a generated
# password) to /root/.kryten-memory.dsn (mode 600).
set -eu

PGVER=17
PGDATA=/var/lib/postgresql/$PGVER/data
PORT=5432
DB=kryten_memory
ROLE=kryten
LOG=/var/log/postgresql.log
DSN_FILE=/root/.kryten-memory.dsn

echo "[1/7] Enabling community repo + installing packages ..."
printf 'https://dl-cdn.alpinelinux.org/alpine/v3.21/main\nhttps://dl-cdn.alpinelinux.org/alpine/v3.21/community\n' > /etc/apk/repositories
apk update -q
apk add -q postgresql$PGVER postgresql$PGVER-contrib postgresql-pgvector openssl

echo "[2/7] Preparing directories ..."
install -d -o postgres -g postgres -m 0700 "$PGDATA"
install -d -o postgres -g postgres -m 0775 /run/postgresql
touch "$LOG"
chown postgres:postgres "$LOG"

echo "[3/7] Initialising cluster (if needed) ..."
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  su postgres -c "initdb -D '$PGDATA' -E UTF8 --auth-local=trust --auth-host=scram-sha-256"
fi

echo "[4/7] Configuring postgresql.conf + pg_hba.conf ..."
CONF="$PGDATA/postgresql.conf"
sed -i "s/^#\?\s*port\s*=.*/port = $PORT/" "$CONF"
sed -i "s/^#\?\s*listen_addresses\s*=.*/listen_addresses = '*'/" "$CONF"
sed -i "s/^#\?\s*password_encryption\s*=.*/password_encryption = scram-sha-256/" "$CONF"
sed -i "s|^#\?\s*unix_socket_directories\s*=.*|unix_socket_directories = '/run/postgresql,/tmp'|" "$CONF"

HBA="$PGDATA/pg_hba.conf"
if ! grep -q "kryten-memory" "$HBA"; then
  {
    echo ""
    echo "# kryten-memory: password auth from the Windows host over WSL2."
    echo "# WSL2's virtual network is host-local (not LAN-routable); scram still"
    echo "# requires the role password. Tighten the CIDR if you prefer."
    echo "host    all    all    0.0.0.0/0    scram-sha-256"
    echo "host    all    all    ::/0         scram-sha-256"
  } >> "$HBA"
fi

echo "[5/7] Starting Postgres ..."
su postgres -c "pg_ctl -D '$PGDATA' -l '$LOG' -w -o '-p $PORT' start" || \
  su postgres -c "pg_ctl -D '$PGDATA' -l '$LOG' -w -o '-p $PORT' restart"

echo "[6/7] Creating role + database + extension ..."
PW="$(openssl rand -hex 20)"
if su postgres -c "psql -p $PORT -tAc \"SELECT 1 FROM pg_roles WHERE rolname='$ROLE'\"" | grep -q 1; then
  su postgres -c "psql -p $PORT -c \"ALTER ROLE $ROLE LOGIN PASSWORD '$PW';\"" >/dev/null
else
  su postgres -c "psql -p $PORT -c \"CREATE ROLE $ROLE LOGIN PASSWORD '$PW';\"" >/dev/null
fi
if ! su postgres -c "psql -p $PORT -tAc \"SELECT 1 FROM pg_database WHERE datname='$DB'\"" | grep -q 1; then
  su postgres -c "createdb -p $PORT -O $ROLE $DB"
fi
su postgres -c "psql -v ON_ERROR_STOP=1 -p $PORT -d $DB -c 'CREATE EXTENSION IF NOT EXISTS vector;' -c 'GRANT ALL ON SCHEMA public TO $ROLE;'" >/dev/null

echo "[7/7] Writing DSN file + enabling auto-start on distro boot ..."
printf 'postgresql://%s:%s@localhost:%s/%s\n' "$ROLE" "$PW" "$PORT" "$DB" > "$DSN_FILE"
chmod 600 "$DSN_FILE"

# Auto-start Postgres whenever the distro launches; a running postmaster keeps
# the WSL2 distro alive so localhost:$PORT stays reachable from Windows. The
# start logic lives in its own script so /etc/wsl.conf needs no nested quoting.
# NOTE: /run is a tmpfs wiped on every distro restart, so the socket directory
# must be recreated here on each boot before Postgres starts.
cat > /usr/local/bin/start-kryten-pg.sh <<EOSTART
#!/bin/sh
install -d -o postgres -g postgres -m 0775 /run/postgresql
# Use the versioned binary directly: /usr/bin/pg_ctl is a version wrapper that
# is not resolvable in the minimal [boot] environment (no interactive PATH).
su postgres -c "/usr/libexec/postgresql$PGVER/pg_ctl -D $PGDATA -l $LOG -o '-p $PORT' -w start"
EOSTART
chmod +x /usr/local/bin/start-kryten-pg.sh

cat > /etc/wsl.conf <<EOWSL
[boot]
command = /usr/local/bin/start-kryten-pg.sh

[user]
default = root
EOWSL

echo "KRYTEN_SETUP_OK pg=$PGVER port=$PORT db=$DB role=$ROLE dsn_file=$DSN_FILE"
