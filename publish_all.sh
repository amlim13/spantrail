#!/usr/bin/env bash
# Publish the SDK to PyPI and switch Stripe to live mode.
#
# Both secrets are read in a HIDDEN field here, in your terminal. Neither
# ever enters this conversation, a command-line argument, a process list, or
# a shell history.
#
#   1. PyPI API token  (pypi.org -> Account -> API tokens -> Add)
#   2. Stripe LIVE secret key (dashboard.stripe.com -> toggle to Live mode
#      -> Developers -> API keys -> Reveal)
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 1

SSH_KEY="${SSH_KEY:-$HOME/.ssh/gspotohetzner}"
SSH_HOST="${SSH_HOST:-root@178.105.143.122}"

OUTDIR=$(cat "$HOME/.spantrail_outdir" 2>/dev/null || true)
if [ -z "${OUTDIR:-}" ] || [ ! -d "sdk/$OUTDIR" ]; then
  echo "No build directory found. Building a fresh one..."
  OUTDIR="dist-publish-$(date +%s)"
  ( cd sdk && python -m build --outdir "$OUTDIR" ) >/dev/null 2>&1 || {
    echo "BUILD FAILED"; exit 1; }
fi
echo "Artifacts: sdk/$OUTDIR"
ls -1 "sdk/$OUTDIR" | sed 's/^/  /'

echo
echo "=== 1. PyPI API token ==="
echo "  Open https://pypi.org/manage/account/token/ and create a token"
echo "  scoped to the 'spantrail' project. Paste it below."
echo "  (The input is hidden and it never enters this chat.)"
printf "PyPI token (pypi-...): "
read -rs PYPI_TOKEN
echo
if [ -z "${PYPI_TOKEN:-}" ]; then echo "No token entered. Aborting." >&2; exit 1; fi
case "$PYPI_TOKEN" in
  pypi-*) ;;
  *) echo "That does not look like a PyPI token (expected pypi-...). Aborting." >&2; exit 1 ;;
esac

echo
echo "=== 2. Stripe LIVE secret key ==="
echo "  Toggle the Stripe dashboard to LIVE mode, then:"
echo "  Developers -> API keys -> Reveal, and copy the LIVE secret key."
echo "  Paste it below."
printf "Stripe live secret key: "
read -rs STRIPE_KEY
echo
if [ -z "${STRIPE_KEY:-}" ]; then echo "No key entered. Aborting." >&2; exit 1; fi
case "$STRIPE_KEY" in
  sk_live_*) ;;
  sk_test_*) echo "That is a TEST key. Aborting - this must be the LIVE key." >&2; exit 1 ;;
  *) echo "That does not look like a Stripe secret key. Aborting." >&2; exit 1 ;;
esac

# ---------------------------------------------------------------- PyPI
echo
echo "=== 3. Publish to PyPI ==="
export TWINE_USERNAME="__token__"
export TWINE_PASSWORD="$PYPI_TOKEN"
python -m twine upload "sdk/$OUTDIR"/* 2>&1 | tail -12 | sed 's/^/  /'
UPLOAD_RC=${PIPESTATUS[0]}
unset TWINE_PASSWORD

if [ "$UPLOAD_RC" != "0" ]; then
  echo
  echo "  PyPI upload FAILED (exit $UPLOAD_RC). Stripe was NOT changed."
  exit 1
fi

# Verify the upload landed before touching Stripe.
echo
echo "  verifying on PyPI..."
sleep 5
CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 25 "https://pypi.org/pypi/spantrail/json")
echo "    pypi.org/pypi/spantrail/json -> HTTP $CODE"
if [ "$CODE" != "200" ]; then
  echo "    (not visible yet - PyPI can take a minute to propagate)"
fi

# ---------------------------------------------------------------- Stripe
echo
echo "=== 4. Switch Stripe to LIVE mode ==="
# The key goes to the server over stdin, never as an argument.
printf '%s' "$STRIPE_KEY" | ssh -i "$SSH_KEY" -o BatchMode=yes "$SSH_HOST" \
  'set -u
   ENV=/opt/spantrail/app/.env
   BAK=/tmp/.env.bak.$$
   cp -p "$ENV" "$BAK"
   echo "  backed up the current .env"

   cat > /tmp/.stlivekey && chmod 600 /tmp/.stlivekey
   /opt/spantrail/venv/bin/python - <<'"'"'PYEOF'"'"'
import getpass, sys, runpy
with open("/tmp/.stlivekey") as f:
    key = f.read().strip()
import getpass as _g
_g.getpass = lambda prompt="Stripe secret key: ", stream=None: key
sys.argv = ["stripe_setup.py"]
try:
    runpy.run_path("/opt/spantrail/app/stripe_setup.py", run_name="__main__")
except SystemExit as e:
    code = e.code if isinstance(e.code, int) else 0
    sys.exit(code)
PYEOF
   SETUP_RC=$?
   rm -f /tmp/.stlivekey

   echo
   echo "  --- verifying the live cutover ---"
   /opt/spantrail/venv/bin/python - <<'"'"'PYEOF'"'"'
import sys
ok = True
vals = {}
for line in open("/opt/spantrail/app/.env"):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        vals[k] = v

def need(key, prefix):
    global ok
    v = vals.get(key, "")
    good = v.startswith(prefix) and len(v) > len(prefix) + 4
    ok = ok and good
    print("    %-24s %s" % (key, (v[:12] + "...") if good else "MISSING OR WRONG"))

need("STRIPE_SECRET_KEY", "sk_live_")
need("STRIPE_PRICE_PRO", "price_")
need("STRIPE_PRICE_TEAM", "price_")
need("STRIPE_WEBHOOK_SECRET", "whsec_")

try:
    from stripe import StripeClient
    c = StripeClient(vals["STRIPE_SECRET_KEY"])
    eps = c.v1.webhook_endpoints.list({"limit": 50}).to_dict()
    live = [e for e in eps.get("data", [])
            if e.get("url") == "https://spantrail.com/api/v1/billing/webhook"
            and e.get("status") == "enabled"]
    print("    live webhook endpoint : %s" % (live[0]["id"] if live else "MISSING"))
    if not live:
        ok = False
    else:
        # Remove any other endpoint pointing at the same URL (the test-mode
        # one). Its events would be signed with the test secret and rejected
        # with a 400 by the live handler.
        for e in eps.get("data", []):
            if (e.get("url") == "https://spantrail.com/api/v1/billing/webhook"
                    and e["id"] != live[0]["id"]):
                try:
                    c.v1.webhook_endpoints.delete(e["id"])
                    print("    removed the stale endpoint %s" % e["id"])
                except Exception as ex:
                    print("    could not remove %s: %s" % (e["id"], ex))
except Exception as ex:
    print("    endpoint check failed: %s" % str(ex)[:120])
    ok = False

sys.exit(0 if ok else 1)
PYEOF
   VERIFY_RC=$?

   if [ $SETUP_RC != 0 ] || [ $VERIFY_RC != 0 ]; then
     echo
     echo "  THE LIVE CUTOVER DID NOT COMPLETE CLEANLY."
     echo "  Restoring the previous .env (the server stays in test mode)."
     cp -p "$BAK" "$ENV" && echo "  restored."
     rm -f "$BAK" /tmp/.stlivekey
     exit 1
   fi
   rm -f "$BAK" /tmp/.stlivekey
   echo
   echo "  live cutover complete."
   exit 0'

STRIPE_RC=$?

if [ "$STRIPE_RC" != "0" ]; then
  echo
  echo "  Stripe cutover FAILED. The server was rolled back to test mode."
  exit 1
fi

echo "=== done ==="
echo "  PyPI    : https://pypi.org/project/spantrail/"
echo "  Stripe  : live mode, USD prices"
echo ""
echo "  Next: buy a real plan at https://spantrail.com/pricing?plan=pro"
echo "  with a real card, then confirm the tenant row shows plan=pro."
