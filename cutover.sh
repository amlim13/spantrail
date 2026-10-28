#!/usr/bin/env bash
# Cut over to the real domain: swap the Caddy config from the self-signed
# placeholder to ACME (Let's Encrypt) for spantrail.com + www.spantrail.com.
#
# Run this ONLY after the A record for spantrail.com points at 178.105.143.122.
# It is idempotent: re-running it just re-checks the certificate.
set -euo pipefail
SSH="ssh -i ~/.ssh/gspotohetzner -o BatchMode=yes root@178.105.143.122"
DOMAIN="spantrail.com"

echo "=== 0. preflight: does DNS point here yet? ==="
# The VPS has neither dig nor nslookup; use getent (glibc resolver) instead.
IPS=$($SSH "getent hosts $DOMAIN | awk '{print \$1}' | head -1" 2>/dev/null || true)
echo "  $DOMAIN -> ${IPS:-<none>}"
if ! echo "$IPS" | grep -q "178.105.143.122"; then
  echo "  ABORT: $DOMAIN does not resolve to 178.105.143.122 yet."
  echo "  Add the A record in Cloudflare, then re-run this script."
  exit 1
fi

echo
echo "=== 0b. is anything already on :80 or :443? ==="
$SSH 'ss -tlnp | grep -E ":(80|443)\s" && echo "  WARNING: something already binds these ports" || echo "  free"'

echo
echo "=== 1. install the ACME Caddyfile ==="
$SSH 'cat > /opt/spantrail/caddy/Caddyfile <<'"'"'CADDYEOF'"'"'
{
	admin off
	email ops@spantrail.com
}

# Real domain, real certificate. Caddy runs as the unprivileged `spantrail`
# user with CAP_NET_BIND_SERVICE, so it can bind :80 for the ACME http-01
# challenge and :443 for TLS.
spantrail.com, www.spantrail.com {
	encode zstd gzip

	handle /health {
		reverse_proxy 127.0.0.1:8080
	}

	handle /api/* {
		reverse_proxy 127.0.0.1:8080
	}

	handle /pricing {
		root * /opt/spantrail/www
		rewrite * /pricing.html
		file_server
	}

	handle /pricing/* {
		root * /opt/spantrail/www
		rewrite * /pricing.html
		file_server
	}

	handle /dashboard {
		root * /opt/spantrail/www
		rewrite * /dashboard.html
		file_server
	}

	handle /dashboard/* {
		root * /opt/spantrail/www
		rewrite * /dashboard.html
		file_server
	}

	# Downloadable SDK wheel.
	handle /dist/* {
		root * /opt/spantrail
		rewrite * /{uri}
		header Content-Type application/octet-stream
		file_server
	}

	handle {
		root * /opt/spantrail/www
		try_files {path} /index.html
		file_server
	}
}
CADDYEOF
chown spantrail:spantrail /opt/spantrail/caddy/Caddyfile
chmod 0644 /opt/spantrail/caddy/Caddyfile
echo "  installed"'

echo
echo "=== 2. validate the config ==="
$SSH 'cd /opt/spantrail/caddy && sudo -u spantrail XDG_DATA_HOME=/opt/spantrail/caddy/data XDG_CONFIG_HOME=/opt/spantrail/caddy/config caddy validate --config Caddyfile --adapter caddyfile 2>&1 | tail -3'

echo
echo "=== 3. restart caddy -> ACME issuance ==="
$SSH 'systemctl restart spantrail-web.service
sleep 8
journalctl -u spantrail-web -n 40 --no-pager | grep -iE "certificate|acme|obtain|error|challenge|loading|listening" | tail -20
echo "--- listeners ---"
ss -tlnp | grep -E ":(80|443)\s" | sed "s/^/  /"'

echo
echo "=== 4. verify the certificate ==="
$SSH 'curl -sI --max-time 15 https://spantrail.com/ | head -5
echo "--- cert chain ---"
echo | openssl s_client -connect 127.0.0.1:443 -servername spantrail.com 2>/dev/null | openssl x509 -noout -subject -issuer -dates 2>/dev/null'

echo
echo "=== 5. external check ==="
curl -sI --max-time 20 https://spantrail.com/ | head -3
curl -sk --max-time 20 https://spantrail.com/health; echo

echo
echo "CUTOVER COMPLETE"
