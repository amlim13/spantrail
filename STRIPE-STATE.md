# SpanTrail - live state (2026-10-27)

Everything below is live and verified end to end.

## The domain

```
https://spantrail.com          -> 200, real Let's Encrypt certificate
https://www.spantrail.com      -> 200, same cert (SAN)
```

```
issuer   : Let's Encrypt (CN = YE2)
subject  : CN = spantrail.com
valid    : 2026-10-27 21:42 UTC  ->  2027-01-25 21:42 UTC
issuer   : Caddy auto-renews
```

DNS (Cloudflare, DNS-only / grey cloud, TTL 300):

| Type | Name | Content | Record id |
|---|---|---|---|
| A | `spantrail.com` | `178.105.143.122` | `5b6fa630652befbf5bd883c0e9b1531c` |
| CNAME | `www.spantrail.com` | `spantrail.com` | `0252c81fedcd44557ebb967a69e33bd4` |

Ports in use: 22 (sshd), 80 (Caddy, ACME + redirect), 443 (Caddy, TLS),
8443 (Caddy, self-signed placeholder - can be removed now), 8080 (uvicorn,
loopback), 5432 (Postgres, loopback).

## Stripe

```
account        : acct_1USITzEg75dpvMZq  (LIM Agentic AI, FR, EUR default)
mode           : TEST
products       : SpanTrail Pro  prod_VWLHNp3mB6Utbr  -> price_1UVIabEg75dpvMZqu85HCZDX  $29/mo
                  SpanTrail Team prod_VWLH6w98scNbhI  -> price_1UVIacEg75dpvMZqTuaPpEox  $99/mo
webhook        : we_1UVIacEg75dpvMZqhjPekswq  enabled, 4 events
portal config  : bpc_1UVIk5Eg75dpvMZqc3UjeWm9  (default)
```

**Delivery proven.** Stripe POSTed to the public endpoint and the server
handled it:

```
Oct 27 22:44:54 uvicorn: 54.187.174.169 - "POST /api/v1/billing/webhook HTTP/1.1" 200 OK
```

`54.187.174.169` is a Stripe IP. The tenant row was updated with the real
`stripe_customer_id` and `stripe_subscription_id` from the event.

Note: the account's default currency is EUR; the prices are USD. Stripe
converts. To bill in EUR instead, change the currency in `stripe_setup.py` and
re-run it - the `lookup_key`s make that non-duplicating.

## Verified

| Check | Result |
|---|---|
| DNS records live on Cloudflare | Yes, both, DNS-only |
| Let's Encrypt cert for apex + www | Yes, `Verify return code: 0 (ok)` |
| HTTPS from outside, no `-k` | 200 on every endpoint |
| HTTP -> HTTPS redirect | Working |
| ACME http-01 challenge served | Yes (log shows the key authorizations) |
| Caddy can bind :80/:443 as non-root | Yes - `CapEff = 0x400` (CAP_NET_BIND_SERVICE) |
| Public URL | `https://spantrail.com` |
| Stripe webhook delivered from the internet | Yes, 200 OK from a Stripe IP |
| Webhook signature verification | Valid accepted, tampered rejected (400) |
| Checkout session creation | 200, real checkout.stripe.com URL |
| Billing portal configuration | Created, default |
| Bots unaffected | 8 timers, 0 failed, 0 restarts |

## The pages

| URL | What it is |
|---|---|
| `/` | Landing page. Pricing cards link to `/pricing?plan=...`. |
| `/pricing` | **The checkout page.** Three plans, each with a button that POSTs to `/api/v1/billing/checkout` and redirects to the Stripe-hosted page. |
| `/dashboard` | Traces, spans, usage, **billing** tab, signup. |
| `/api/docs` | OpenAPI reference. |

The billing tab in the dashboard shows the current plan, the three plans side
by side, a "Switch to X" button that opens Stripe Checkout, and a "Manage
subscription" button that opens the Stripe billing portal.

`www/pricing_dom_test.cjs` runs the pricing page's JavaScript against a
stubbed DOM and a mocked fetch, and asserts that clicking "Upgrade to Pro"
calls `/api/v1/billing/checkout` with `plan=pro` and then navigates to the
returned Stripe URL. Run it with:

```
node www/pricing_dom_test.cjs www/pricing.html
```

## Still to do

1. **Revoke the Cloudflare token** - https://dash.cloudflare.com/profile/api-tokens
   -> `spantrail-dns` -> Revoke. The DNS records stay; only the token dies.
2. **Buy a Pro plan through the real checkout UI** - open
   `https://spantrail.com/pricing?plan=pro`, paste the API key, click
   "Upgrade to Pro", pay with `4242 4242 4242 4242`. Then confirm the tenant
   row flips to `plan=pro`.
3. **Test cancellation** - cancel in the Stripe test dashboard, confirm
   `status='cancelled'`.
4. **Push the repo to GitHub** (needs a token) and publish to PyPI.
5. **Go live on Stripe** - only after 2 and 3 pass. Create the products again
   in live mode (prices are mode-specific) and re-run `stripe_run.sh` with the
   live key.
6. **Remove the :8443 placeholder** once nothing depends on it.
