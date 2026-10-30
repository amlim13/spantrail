# Release checklist

Both steps need a secret that only the operator can supply. `publish_all.sh`
reads both in a hidden terminal field - neither enters the conversation, a
command-line argument, a process list, or a shell history.

**In PowerShell or cmd** (this is the one to use - PowerShell 5.1 does not
accept `&&`):

```
release.bat
```

**In Git Bash or WSL:**

```bash
bash publish_all.sh
```

Both do the same thing. The script publishes to PyPI **first** and verifies
the upload landed on pypi.org. Only then does it touch Stripe. If the PyPI
upload fails, Stripe is not touched at all. The Stripe step backs up
`/opt/spantrail/app/.env` and restores it if the cutover does not complete
cleanly, and the Stripe key is byte-verified on the server before use.

### If the script cannot find the deploy key

The key lives in the WSL home (`~/.ssh/gspotohetzner`), not the Windows one.
The script detects which home has it and uses WSL's `ssh` when that is where
it lives. To override:

```bash
SSH_KEY=/path/to/key SSH_BIN=ssh bash publish_all.sh
```

## Step 1 - the PyPI token

1. https://pypi.org/manage/account/token/ -> Add API token
2. Scope it to the `spantrail` project only.
3. It starts with `pypi-`.

## Step 2 - the Stripe LIVE secret key

1. Toggle the Stripe dashboard to **Live mode** (top right).
2. Developers -> API keys -> Reveal -> copy the **secret** key.
3. It starts with `sk_live_`.

The script refuses a `sk_test_` key.

## Before running it

| Check | Why |
|---|---|
|---|---|
| The PyPI name is still free | `curl -s -o /dev/null -w '%{http_code}' https://pypi.org/pypi/spantrail/json` -> 404 means free |
| `twine check dist/*` passes | A metadata error blocks the upload |
| The build is current | `cd sdk && python -m build` |
| CI is green | The secret-scan gate must pass before publishing |

## What the Stripe step changes

Live-mode objects are a separate namespace in Stripe:

- The live products/prices list starts empty -> **new** products and prices
  are created. The test `price_...` ids do not carry over.
- The live webhook endpoints list starts empty -> a **new** endpoint is
  created. The script then deletes the test-mode endpoint that still points
  at the production URL, because its events would be signed with the test
  secret and rejected with a 400 by the live handler.
- `STRIPE_SECRET_KEY`, `STRIPE_PRICE_PRO`, `STRIPE_PRICE_TEAM` and
  `STRIPE_WEBHOOK_SECRET` in `/opt/spantrail/app/.env` are all replaced.

The existing test subscription and its customer stay in Stripe, but the
server now uses live mode, so the tenant row's `stripe_customer_id` points at
a test customer until a real purchase replaces it.

## Currency

Prices are **USD** (`$29` and `$99`). The account's default currency is EUR,
so Stripe settles to EUR while charging the customer in USD. If you want to
charge EUR instead, change `"currency": "usd"` in `stripe_setup.py` **before**
running the live setup - changing it afterwards means creating new prices.

## After the live cutover

1. Buy a real plan: https://spantrail.com/pricing?plan=pro
2. Confirm the tenant row:
   ```bash
   ssh $SSH_HOST "sudo -u spantrail /usr/lib/postgresql/16/bin/psql \
     -h /opt/spantrail/pgdata -U spantrail -d spantrail -c \
     'SELECT name, plan, status, stripe_customer_id FROM tenants'"
   ```
   `plan` = `pro`, `status` = `active`, and a **live** customer id
   (`cus_...` that is not the old test one).
3. Test cancellation in the live Stripe dashboard -> `status='cancelled'`.
4. Update `STRIPE-STATE.md`.

## Verifying the PyPI release

```bash
curl -s https://pypi.org/pypi/spantrail/json | python -c "import sys,json; d=json.load(sys.stdin); print(d['info']['version'])"
pip install spantrail
```
