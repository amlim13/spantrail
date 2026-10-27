#!/usr/bin/env bash
# SpanTrail installer - runs as root on the Hetzner VPS.
# Installs packages, creates the spantrail user, lays down the app tree, initialises
# Postgres, and installs systemd units. Idempotent.
set -euo pipefail

APP=/opt/spantrail
SRC=/tmp/spantrail-src
LOG_PREFIX="[spantrail-install]"

say(){ echo "$LOG_PREFIX $*"; }

# ---------------------------------------------------------------- packages
export DEBIAN_FRONTEND=noninteractive
say "installing packages (no upgrades, additions only)"
apt-get install -y --no-install-recommends \
  postgresql-16 postgresql-client-16 caddy python3-venv python3-pip ca-certificates \
  >/tmp/spantrail-apt.log 2>&1 || { tail -40 /tmp/spantrail-apt.log; exit 1; }
say "packages ok"

# apt auto-creates and starts a default cluster (16/main) on port 5432.
# We run our own cluster inside spantrail.slice, so retire the distro one.
say "retiring the auto-created default postgres cluster"
systemctl stop postgresql.service 2>/dev/null || true
systemctl disable postgresql.service 2>/dev/null || true
if [ -d /var/lib/postgresql/16/main ] && [ -f /var/lib/postgresql/16/main/PG_VERSION ]; then
  pg_dropcluster --stop 16 main 2>/dev/null \
    || su - postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/16/main stop" 2>/dev/null || true
  say "dropped cluster 16/main"
fi
systemctl mask postgresql.service 2>/dev/null || true
say "default cluster out of the way"

# The distro caddy package ships a default site on :80 that auto-starts.
# We run our own caddy (spantrail-web) on :8443, so take the distro one down.
say "retiring the distro caddy service"
systemctl stop caddy.service 2>/dev/null || true
systemctl disable caddy.service 2>/dev/null || true
systemctl mask caddy.service 2>/dev/null || true
say "distro caddy masked"

# ---------------------------------------------------------------- user
if ! id spantrail >/dev/null 2>&1; then
  say "creating system user spantrail (no login, no home)"
  useradd --system --create-home --home-dir "$APP" --shell /usr/sbin/nologin spantrail
fi
say "user spantrail: $(id spantrail)"

# Run a command as spantrail. Prefer sudo, fall back to runuser.
as_spantrail(){
  if command -v sudo >/dev/null 2>&1; then
    sudo -u spantrail "$@"
  else
    runuser -u spantrail -- "$@"
  fi
}

# ---------------------------------------------------------------- tree
say "laying out $APP"
install -d -o spantrail -g spantrail -m 0755 "$APP" "$APP/app" "$APP/www" "$APP/caddy" "$APP/venv" "$APP/pgdata"
install -d -o spantrail -g spantrail -m 0700 "$APP/app"
install -d -o spantrail -g spantrail -m 0750 "$APP/caddy"

# ---------------------------------------------------------------- app files
say "installing application files"
install -o spantrail -g spantrail -m 0644 "$SRC/app/main.py"       "$APP/app/main.py"
install -o spantrail -g spantrail -m 0644 "$SRC/app/db.py"         "$APP/app/db.py"
install -o spantrail -g spantrail -m 0644 "$SRC/app/auth.py"       "$APP/app/auth.py"
install -o spantrail -g spantrail -m 0644 "$SRC/app/billing.py"    "$APP/app/billing.py"
install -o spantrail -g spantrail -m 0644 "$SRC/app/admin.py"      "$APP/app/admin.py"
install -o spantrail -g spantrail -m 0644 "$SRC/app/retention.py"  "$APP/app/retention.py"
install -o spantrail -g spantrail -m 0644 "$SRC/app/schema.sql"    "$APP/app/schema.sql"
install -o spantrail -g spantrail -m 0644 "$SRC/app/requirements.txt" "$APP/app/requirements.txt"

say "installing web assets"
install -o spantrail -g spantrail -m 0644 "$SRC/www/index.html"    "$APP/www/index.html"
install -o spantrail -g spantrail -m 0644 "$SRC/www/dashboard.html" "$APP/www/dashboard.html"

say "installing caddy config"
install -o spantrail -g spantrail -m 0644 "$SRC/caddy/Caddyfile"   "$APP/caddy/Caddyfile"

# Self-signed cert for the placeholder hostname. Replaced by a real ACME cert
# once the domain points at this host.
if [ ! -f "$APP/caddy/tls/spantrail.crt" ]; then
  say "generating self-signed TLS cert for spantrail.local"
  install -d -o spantrail -g spantrail -m 0750 "$APP/caddy/tls"
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$APP/caddy/tls/spantrail.key" -out "$APP/caddy/tls/spantrail.crt" \
    -days 825 -subj "/CN=spantrail.local" \
    -addext "subjectAltName=DNS:spantrail.local,DNS:localhost,IP:127.0.0.1" \
    >/tmp/spantrail-cert.log 2>&1 || { tail -10 /tmp/spantrail-cert.log; exit 1; }
  chown spantrail:spantrail "$APP/caddy/tls/spantrail.key" "$APP/caddy/tls/spantrail.crt"
  chmod 0640 "$APP/caddy/tls/spantrail.key" "$APP/caddy/tls/spantrail.crt"
  say "cert ok"
fi

# ---------------------------------------------------------------- venv
# The venv was created under a previous install path. Moving the app directory
# breaks the shebang in venv/bin/* ("cannot execute: required file not found"),
# so verify the interpreter actually runs and rebuild the venv if it does not.
venv_broken=0
if [ -x "$APP/venv/bin/python" ]; then
  "$APP/venv/bin/python" -c "import sys" >/dev/null 2>&1 || venv_broken=1
else
  venv_broken=1
fi
# venv/bin/pip and friends are scripts with a hardcoded shebang pointing at the
# venv's original path. After the app directory moves, the shebang is stale and
# the script fails with "cannot execute: required file not found" even though
# venv/bin/python itself still works. So test pip explicitly.
if [ "$venv_broken" = "0" ]; then
  "$APP/venv/bin/pip" --version >/dev/null 2>&1 || venv_broken=1
fi
if [ "$venv_broken" = "1" ]; then
  say "venv is broken (moved install path) - rebuilding"
  rm -rf "$APP/venv"
  python3 -m venv "$APP/venv"
  chown -R spantrail:spantrail "$APP/venv"
fi
if [ ! -x "$APP/venv/bin/pip" ]; then
  say "creating venv"
  python3 -m venv "$APP/venv"
  chown -R spantrail:spantrail "$APP/venv"
fi
say "installing python dependencies"
"$APP/venv/bin/pip" install --quiet --upgrade pip >/tmp/spantrail-pip.log 2>&1
"$APP/venv/bin/pip" install --quiet -r "$APP/app/requirements.txt" >>/tmp/spantrail-pip.log 2>&1 \
  || { tail -40 /tmp/spantrail-pip.log; exit 1; }
say "python deps ok"

# ---------------------------------------------------------------- env file
if [ ! -f "$APP/app/.env" ]; then
  say "generating .env (secrets)"
  ADMIN_TOKEN="$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 32)"
  DB_PASS="$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 32)"
  {
    echo "DATABASE_URL=postgresql://spantrail:${DB_PASS}@127.0.0.1:5432/spantrail"
    echo "ADMIN_TOKEN=${ADMIN_TOKEN}"
    echo "PUBLIC_URL=https://178.105.143.122:8443"
    echo "RETENTION_DAYS=30"
    echo "STRIPE_SECRET_KEY="
    echo "STRIPE_WEBHOOK_SECRET="
    echo "STRIPE_PRICE_PRO="
    echo "STRIPE_PRICE_TEAM="
  } > "$APP/app/.env"
  chmod 0600 "$APP/app/.env"
  chown spantrail:spantrail "$APP/app/.env"
  say ".env created"
else
  say ".env already present, leaving it alone"
fi

# ---------------------------------------------------------------- units
say "installing systemd units"
for u in spantrail.slice spantrail-db.service spantrail-api.service spantrail-web.service \
         spantrail-retention.service spantrail-retention.timer; do
  install -m 0644 "$SRC/units/$u" "/etc/systemd/system/$u"
done
# Retiring the old obsv units (first run of the rename).
rm -f /etc/systemd/system/obsv.slice \
      /etc/systemd/system/obsv-db.service /etc/systemd/system/obsv-api.service \
      /etc/systemd/system/obsv-web.service /etc/systemd/system/obsv-retention.service \
      /etc/systemd/system/obsv-retention.timer
systemctl daemon-reload
systemctl enable spantrail-retention.timer >/dev/null 2>&1 || true

# ---------------------------------------------------------------- postgres
if [ ! -f "$APP/pgdata/PG_VERSION" ]; then
  say "initialising postgres cluster"
  chown spantrail:spantrail "$APP/pgdata"
  as_spantrail /usr/lib/postgresql/16/bin/initdb -D "$APP/pgdata" -U spantrail \
     --auth-local=trust --auth-host=scram-sha-256 --encoding=UTF8 >/tmp/spantrail-initdb.log 2>&1 \
     || { tail -30 /tmp/spantrail-initdb.log; exit 1; }
fi

say "tuning postgres for a small box"
chown spantrail:spantrail "$APP/pgdata"
chmod 0700 "$APP/pgdata"
cat > "$APP/pgdata/postgresql.auto.conf" <<'PGCONF'
shared_buffers = 128MB
effective_cache_size = 384MB
work_mem = 2MB
maintenance_work_mem = 32MB
max_connections = 40
listen_addresses = '127.0.0.1'
port = 5432
unix_socket_directories = '/opt/spantrail/pgdata'
wal_compression = on
checkpoint_completion_target = 0.9
PGCONF
chown spantrail:spantrail "$APP/pgdata/postgresql.auto.conf"

say "starting postgres (first boot)"
systemctl daemon-reload
systemctl enable --now spantrail-db.service
for i in $(seq 1 30); do
  if as_spantrail /usr/lib/postgresql/16/bin/pg_isready -h 127.0.0.1 -p 5432 -q; then break; fi
  sleep 1
done
as_spantrail /usr/lib/postgresql/16/bin/pg_isready -h 127.0.0.1 -p 5432 \
  || { echo "postgres did not become ready"; journalctl -u spantrail-db -n 40; exit 1; }
say "postgres ready"

say "creating role and database"
DB_PASS=$(grep '^DATABASE_URL=' "$APP/app/.env" | sed -E 's|.*://spantrail:([^@]*)@.*|\1|')
PSQL="/usr/lib/postgresql/16/bin/psql -h $APP/pgdata -p 5432 -d postgres -v ON_ERROR_STOP=1"
as_spantrail $PSQL -c "ALTER ROLE spantrail PASSWORD '$DB_PASS';" >/dev/null
as_spantrail $PSQL -tAc "SELECT 1 FROM pg_database WHERE datname='spantrail'" | grep -q 1 \
  || as_spantrail $PSQL -c "CREATE DATABASE spantrail OWNER spantrail;"
say "database ready"

say "starting api and web"
# restart (not enable --now): enable --now is a no-op on an already-active unit,
# which would leave a stale config loaded.
systemctl enable spantrail-api.service spantrail-web.service >/dev/null 2>&1
systemctl restart spantrail-api.service
# Wait for the API to actually accept connections before starting the edge,
# otherwise Caddy returns 502 during the race.
api_up=0
for i in $(seq 1 30); do
  if curl -s -o /dev/null --max-time 3 http://127.0.0.1:8080/health; then api_up=1; break; fi
  sleep 1
done
[ "$api_up" = "1" ] || { say "API did not come up"; journalctl -u spantrail-api -n 30 --no-pager; exit 1; }
say "api ready"
systemctl restart spantrail-web.service
systemctl enable --now spantrail-retention.timer

# ---------------------------------------------------------------- verify
sleep 6
say "--- unit status ---"
for u in spantrail-db spantrail-api spantrail-web; do
  printf '%-12s %s / %s\n' "$u" \
    "$(systemctl is-active $u.service)" \
    "$(systemctl show $u.service -p MemoryCurrent --value)"
done

say "--- stability check (3 samples, 3s apart) ---"
stable=1
for i in 1 2 3; do
  a=$(systemctl is-active spantrail-web.service)
  b=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 8 https://127.0.0.1:8443/health || echo 000)
  say "  sample $i: spantrail-web=$a http=$b"
  [ "$a" = "active" ] && [ "$b" = "200" ] || stable=0
  sleep 3
done
if [ "$stable" != "1" ]; then
  say "spantrail-web is NOT stable - dumping caddy log"
  journalctl -u spantrail-web -n 30 --no-pager | tail -30
  exit 1
fi
say "spantrail-web stable"

say "--- health ---"
curl -sk --max-time 10 https://127.0.0.1:8443/health || \
  curl -s --max-time 10 http://127.0.0.1:8080/health || echo "health check failed"

say "INSTALL COMPLETE"
