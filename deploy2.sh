#!/usr/bin/env bash
# Deploy the spantrail tree to the VPS (after migration) and verify.
set -euo pipefail
LOCAL="${LOCAL:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/gspotohetzner}"
SSH_HOST="${SSH_HOST:-root@178.105.143.122}"
SSH="ssh -i $SSH_KEY -o BatchMode=yes -o ConnectTimeout=15 $SSH_HOST"

echo "--- staging tree on remote ---"
$SSH "rm -rf /tmp/spantrail-src && mkdir -p /tmp/spantrail-src"

for d in app www caddy units sdk; do
  echo "uploading $d/"
  tar -C "$LOCAL" -czf - "$d" | $SSH "tar -C /tmp/spantrail-src -xzf -"
done

echo "uploading install.sh"
tr -d '\r' < "$LOCAL/install.sh" | $SSH "cat > /tmp/spantrail-src/install.sh && chmod +x /tmp/spantrail-src/install.sh"

echo "--- running installer ---"
$SSH "bash /tmp/spantrail-src/install.sh" 2>&1 | tail -40
