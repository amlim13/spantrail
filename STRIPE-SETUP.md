# Stripe setup - one command

Everything below is automated over the Stripe API. You run one command, paste
your secret key into a hidden prompt, and the rest happens.

## Run it

From this directory (in WSL / Git Bash):

```bash
bash stripe_run.sh
```

You'll see:

```
Stripe secret key:
```

Paste your key and press Enter. **The input is hidden** - nothing echoes. The
key goes straight to the server over SSH stdin. It never appears in:
- this conversation
- a command-line argument (so not in the process list)
- any shell history, local or remote
- the repo

The script then does, over the API:

1. **Verifies the key** and prints the account (id, country, currency, and whether it's test or live mode)
2. **Creates the products and prices** - `SpanTrail Pro` ($29/mo) and `SpanTrail Team` ($99/mo), each with a `lookup_key` so re-running reuses them instead of creating duplicates
3. **Creates the webhook endpoint** at `https://spantrail.com/api/v1/billing/webhook` for the four events we handle, and captures its signing secret
4. **Writes the `.env`** - `STRIPE_SECRET_KEY`, `STRIPE_PRICE_PRO`, `STRIPE_PRICE_TEAM`, `STRIPE_WEBHOOK_SECRET` - `chmod 0600`, owner `spantrail`
5. **Restarts the API** and verifies the endpoints respond
6. Prints the checkout test command

## Before you run it

**Get the key:** https://dashboard.stripe.com/test/apikeys -> Reveal the Secret key (`sk_test_...`).

Use **test mode** first. Live mode works too (the script warns you loudly), but don't go live until a checkout has been verified end to end.

## Two-phase run (domain not live yet)

The webhook endpoint's URL must be the real domain, because Stripe validates TLS when it delivers. If `spantrail.com` doesn't resolve yet, do it in two steps:

```bash
bash stripe_run.sh --skip-webhook    # products + prices + secret key
# ...add the A record, let me run the ACME cutover...
bash stripe_run.sh                    # now creates the webhook endpoint too
```

The second run reuses the products and prices from the first (matched by `lookup_key`) and only adds the webhook.

## Verifying it worked

```bash
ssh $SSH_HOST "grep -E '^STRIPE_' /opt/spantrail/app/.env | sed 's/=.*/=<set>/'"
```

All four should read `<set>`. Then, from the dashboard, get a tenant's API key and start a checkout:

```bash
curl -X POST https://spantrail.com/api/v1/billing/checkout \
  -H "X-API-Key: spantrail_sk_..." \
  -H "Content-Type: application/json" \
  -d '{"plan":"pro"}'
```

You get back `{"url": "https://checkout.stripe.com/..."}`. Open it and use:
- **Card**: `4242 4242 4242 4242`
- **Expiry**: any future date
- **CVC**: any 3 digits

On success the webhook fires and the tenant row updates:

```bash
ssh $SSH_HOST "sudo -u spantrail /usr/lib/postgresql/16/bin/psql \
  -h /opt/spantrail/pgdata -U spantrail -d spantrail -c \
  'SELECT name, plan, status, stripe_customer_id FROM tenants'"
```

Expected: `plan` becomes `pro`, `status` stays `active`, and `stripe_customer_id` is populated.

Then test the failure path: cancel the subscription in the Stripe test dashboard -> `customer.subscription.deleted` -> our row flips to `status='cancelled'`.

## Rollback / troubleshooting

| Symptom | Fix |
|---|---|
| "the key was rejected by Stripe" | Wrong key, or it has whitespace. Copy it again from the dashboard. |
| "could not create the webhook endpoint" | The domain does not resolve yet. Use `--skip-webhook` and finish after the cutover. |
| Checkout returns 503 `stripe_not_configured` | `STRIPE_SECRET_KEY` is empty in the `.env`. Re-run the script. |
| Checkout returns 503 `missing_price_id_for_pro` | The price wasn't created. Re-run the script - it will create it. |
| Webhook returns 400 | The signing secret in the `.env` doesn't match the endpoint's. Re-run the script; it reuses the endpoint and rewrites the secret. |
| Prices duplicated | Shouldn't happen - the script matches on `lookup_key`. If it did, archive the old price in the dashboard (`active: false`). |

## Going live

Do not swap to a live key until a test checkout has completed, the webhook has
been confirmed to update the tenant row, and cancellation has been tested.

Then:
1. Stripe Dashboard -> toggle to **Live mode**
2. Create the two products **again** in live mode (prices are mode-specific - a test `price_...` will not work with a live key)
3. Re-run `bash stripe_run.sh` with the **live** key (`sk_live_...`)
4. Re-create the webhook endpoint in live mode (test endpoints don't receive live events)

## Pricing rationale

| Plan | Price | Events/mo | Retention | Why |
|---|---|---|---|---|
| Free | $0 | 50k | 30d | Enough for a real agent to evaluate; a genuine upgrade trigger at 50k events |
| Pro | $29 | 1M | 30d | ~60x the free tier. A single busy agent doing 100 calls/day with 5 spans each = 15k events/mo. 1M covers a small team |
| Team | $99 | 10M | 90d | Adds retention (the thing enterprises actually buy) and workspaces |

Storage math: a span row is roughly 600 bytes with JSONB input/output. 1M
spans/mo is about 600 MB/mo/tenant before Postgres overhead and indexes, call
it 1 GB. At 90 days on the Team plan that is about 9 GB per Team tenant. On a
66 GB disk with Postgres capped at 768 MB RAM, expect to hold roughly 40-50
Team tenants before the disk becomes the constraint. When it does, the fix is
a second Hetzner box - not a rewrite.

## What's already been verified

| Test | Result |
|---|---|
| `stripe_run.sh` pipes the key without exposing it | Not in the process list, not in either shell history, temp file deleted |
| A failed run does not modify the `.env` | md5 identical before/after |
| The setup script reaches Stripe's auth check | `Invalid API Key provided: sk_test_***0000` |
| `accounts.retrieve()` needs an id | Fixed to list-then-retrieve |
| stripe-python v16 service signatures | `create`/`list` take a positional params dict; `delete` takes the id positionally |
| Products, prices and webhook endpoint creation | Implemented with `lookup_key` / URL matching for idempotency |
