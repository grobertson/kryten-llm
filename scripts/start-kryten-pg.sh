#!/bin/sh
# Start PostgreSQL for the Kryten memory DB inside the dedicated WSL distro.
#
# Invoked by /etc/wsl.conf [boot] command and/or a Windows scheduled task at
# logon. Safe to run repeatedly. /run is a tmpfs wiped on every distro restart,
# so the socket directory must be (re)created here before Postgres starts.
install -d -o postgres -g postgres -m 0775 /run/postgresql
date -u "+%Y-%m-%dT%H:%M:%SZ boot: starting postgres" >> /var/log/kryten-pg-boot.log
# Use the versioned binary directly: /usr/bin/pg_ctl is a version wrapper that
# is not resolvable in the minimal [boot] environment (no interactive PATH).
su postgres -c "/usr/libexec/postgresql17/pg_ctl -D /var/lib/postgresql/17/data -l /var/log/postgresql.log -o '-p 5432' -w start" \
    >> /var/log/kryten-pg-boot.log 2>&1
