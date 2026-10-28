#!/usr/bin/env bash
# Interactive Stripe setup for SpanTrail.
#
# Prompts for the Stripe secret key in a hidden field HERE (not in chat), then
# copies it to the VPS over SSH and runs stripe_setup.py there, which does the
# whole configuration over the Stripe API.
#
# Usage:
#   bash stripe_run.sh              # full setup (products, prices, webhook)
#   bash stripe_run.sh --skip-webhook   # products and prices only
set -euo pipefail

SSH_HOST="${SSH_HOST:-root@178.105.143.122}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/gspotohetzner}"
REMOTE_SCRIPT="/opt/spantrail/app/stripe_setup.py"
EXTRA=""
[ "${1:-}" = "--skip-webhook" ] && EXTRA="--skip-webhook"

echo "SpanTrail Stripe setup"
echo "======================================================================"
echo
echo "  1. Open https://dashboard.stripe.com/test/apikeys"
echo "  2. Reveal the Secret key (starts with sk_test_)"
echo "  3. Paste it below - the input is hidden and it never enters this chat."
echo
printf "Stripe secret key: "
read -rs SECRET
echo
echo

if [ -z "$SECRET" ]; then
  echo "No key entered. Aborting." >&2
  exit 1
fi

case "$SECRET" in
  sk_test_*|sk_live_*) ;;
  *) echo "That does not look like a Stripe secret key. Aborting." >&2; exit 1 ;;
esac

echo "Connecting to the VPS..."
if ! ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=15 "$SSH_HOST" "true" 2>/dev/null; then
  echo "Cannot reach the VPS at $SSH_HOST" >&2
  exit 1
fi

# Copy the key to the server over stdin (never as a command-line argument, so
# it does not appear in the process list or in ~/.bash_history on the VPS).
echo "Running the setup on the VPS..."
printf '%s' "$SECRET" | ssh -i "$SSH_KEY" -o BatchMode=yes "$SSH_HOST" \
  "cat > /tmp/.stkey && chmod 600 /tmp/.stkey && \
   /opt/spantrail/venv/bin/python - <<'PYEOF'
import getpass, sys, runpy, os
# Read the key from the file we just piped in, and feed it to getpass.
with open('/tmp/.stkey') as f:
    key = f.read().strip()
import getpass as _g
_g.getpass = lambda prompt='Stripe secret key: ', stream=None: key
sys.argv = ['stripe_setup.py'] + sys.argv[1:]
try:
    runpy.run_path('/opt/spantrail/app/stripe_setup.py', run_name='__main__')
except SystemExit as e:
    # Preserve the exit code but ALWAYS clean up the key file.
    code = e.code if isinstance(e.code, int) else 0
    sys.exit(code)
PYEOF
  status=\$?; rm -f /tmp/.stkey; exit \$status" $EXTRA

echo
echo "Setup finished. The secret key was not saved anywhere in the conversation."
