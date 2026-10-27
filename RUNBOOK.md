# SpanTrail - Operator Runbook

Agent observability SaaS running on the Hetzner VPS `178.105.143.122`, sharing
the host with the HYPE/ETH trading bots. This file is the only thing you need
to operate it.

Renamed from "Obsv" to "SpanTrail" on 2026-10-27 after the domain
`spantrail.com` was purchased. The `.com` was chosen over `tokentrail.*`
because "TokenTrail" is already in active use by several products in this
exact category.

## TL;DR

```bash
# service state
systemctl status spantrail-db spantrail-api spantrail-web

# restart everything (safe, ~5s)
systemctl restart spantrail-db spantrail-api spantrail-web

# health
curl -sk https://127.0.0.1:8443/health

# redeploy from source (run from the local repo dir)
bash deploy2.sh

# Stripe setup (prompts for the key in a hidden field)
bash stripe_run.sh
```

## Layout

| Path | What |
|---|---|
| `/opt/spantrail/app/` | FastAPI app (`main.py`, `db.py`, `auth.py`, `billing.py`, `admin.py`, `retention.py`, `stripe_setup.py`, `schema.sql`) |
| `/opt/spantrail/app/.env` | Secrets. `chmod 0600`, owner `spantrail`. **Never paste its contents into chat.** |
| `/opt/spantrail/venv/` | Python venv (FastAPI, uvicorn, psycopg2, stripe 16.x) |
| `/opt/spantrail/pgdata/` | PostgreSQL 16 data dir (`0700`, owner `spantrail`) |
| `/opt/spantrail/caddy/` | Caddyfile + `tls/` (self-signed until the ACME cutover) |
| `/opt/spantrail/www/` | `index.html` (landing), `dashboard.html` |
| `/opt/spantrail/dist/` | Built SDK wheel (`spantrail-0.1.0-py3-none-any.whl`) |
| `/tmp/spantrail-src` | Source tree uploaded by `deploy2.sh` |

## Units and resource caps

All three units live in the `spantrail.slice` cgroup. The trading bots are in
the default slice and are NOT in the same cgroup, so a runaway in SpanTrail
cannot trigger an OOM kill of a bot.

| Unit | MemoryMax | CPUQuota | Notes |
|---|---|---|---|
| `spantrail-db` | 768M | 20% | Postgres, `shared_buffers=128MB` |
| `spantrail-api` | 2G | 40% | uvicorn, 2 workers, port 8080 (loopback only) |
| `spantrail-web` | 128M | 10% | Caddy, TLS on :8443 |

The slice itself enforces `MemoryMax=2G` / `CPUQuota=40%` as a backstop.
`MemorySwapMax=0` on every unit: no swap, so a leak OOMs the SpanTrail process
instead of thrashing the host.

`spantrail-retention.timer` runs the 30-day purge at 03:17 UTC nightly.

`spantrail-web` has `AmbientCapabilities=CAP_NET_BIND_SERVICE` so the
unprivileged `spantrail` user can bind :80 and :443 (needed for ACME).

## Tenants and API keys

Keys are shown ONCE. Only a SHA-256 hash is stored.

```bash
cd /opt/spantrail/app
sudo -u spantrail /opt/spantrail/venv/bin/python admin.py tenant-create --name "Acme" --email dev@acme.com --plan pro
sudo -u spantrail /opt/spantrail/venv/bin/python admin.py tenant-list
sudo -u spantrail /opt/spantrail/venv/bin/python admin.py key-rotate --tenant <uuid>
```

## Ports

| Port | Bound to | Service |
|---|---|---|
| 22 | 0.0.0.0 | sshd (pre-existing) |
| 80 | 0.0.0.0 | Caddy (ACME http-01 + redirect) - after cutover |
| 443 | 0.0.0.0 | Caddy (TLS) - after cutover |
| 8443 | 0.0.0.0 | Caddy (self-signed placeholder, current) |
| 8080 | 127.0.0.1 | uvicorn (never public) |
| 5432 | 127.0.0.1 | Postgres (never public) |

## Domain cutover (pending)

`spantrail.com` is registered at Cloudflare (NS `aitana`/`gerardo.ns.cloudflare.com`).
**The A record has not been added yet.** Once it points at `178.105.143.122`:

1. Run `cutover.sh` from the local repo dir. It validates the config, swaps
   Caddy to ACME for `spantrail.com` + `www.spantrail.com`, and verifies the
   Let's Encrypt certificate.
2. `curl -sI https://spantrail.com/` should return 200 with a real cert.

The cutover script is idempotent and aborts safely if DNS has not propagated.

## Stripe

Configured over the API by `stripe_run.sh` (see `STRIPE-SETUP.md`). It
prompts for the secret key in a hidden field and pipes it to the server over
stdin - the key never appears in a command-line argument, a process list, a
shell history, or this chat.

It creates the products and prices, the webhook endpoint, writes the four
`STRIPE_*` values into the `.env`, and restarts the API.

## Backups

```bash
sudo -u spantrail /usr/lib/postgresql/16/bin/pg_dump -h /opt/spantrail/pgdata -U spantrail -d spantrail \
  | gzip > /opt/spantrail/backup-$(date +%F).sql.gz
```

## Troubleshooting

| Symptom | Check |
|---|---|
| `spantrail-web` flapping | `journalctl -u spantrail-web -n 50`. Validate: `caddy validate --config /opt/spantrail/caddy/Caddyfile --adapter caddyfile` |
| `spantrail-api` returning 502 | API is down or not bound yet. `systemctl status spantrail-api` |
| "cannot execute: required file not found" on a venv script | The app dir was moved and the venv shebangs went stale. The installer detects and rebuilds it. |
| SDK "sends" but nothing arrives | The SDK swallows errors by design. Check the API log for `POST /api/v1/ingest` lines. |
| `422` on ingest | Payload shape mismatch - the API expects one object `{traces:[],spans:[],logs:[]}`, not a list. |
| Bots seem slow | Check `systemctl show spantrail.slice -p MemoryCurrent` and `free -m`. |

## Operating rules (from the trading skill)

- Never overwrite, print or leak `/opt/spantrail/app/.env` or any bot `.env`.
- Never touch `/opt/hype_bot`, `/opt/hypeTrend1h`, `/home/yusuf/`.
- Exchange reads are fine; no order placement, no live/dry flips.
- The `spantrail` user has no sudo and cannot read bot secrets - keep it that way.
- SpanTrail must never make outbound calls to LLM providers. Buyer keys stay in
  the buyer's own code; SpanTrail only receives events.
