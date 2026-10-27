# SpanTrail - Stripe state (as configured on 2026-10-27)

Everything below is set up and verified. The secret key is NOT in this file
(it lives only in `/opt/spantrail/app/.env` on the server).

## Account

```
account id     : acct_1USITzEg75dpvMZq
business name  : LIM Agentic AI
country        : FR
default ccy    : eur
charges        : enabled
payouts        : enabled
card_payments  : active
mode           : TEST
```

**Note:** the account's default currency is EUR. Our prices are denominated in
USD (see below). Stripe handles this: the charge is created in USD and
converted at the card network's rate. If you would rather bill in EUR, the
prices need to be recreated in EUR - the `lookup_key`s make that a one-command
change (re-run `stripe_run.sh` after updating the currency in the script).

## Products and prices (created, test mode)

| Plan | Product | Price | Amount | Interval |
|---|---|---|---|---|
| Pro | `prod_VWLHNp3mB6Utbr` | `price_1UVIabEg75dpvMZqu85HCZDX` | $29.00 USD | month |
| Team | `prod_VWLH6w98scNbhI` | `price_1UVIacEg75dpvMZqTuaPpEox` | $99.00 USD | month |

Both prices carry a `lookup_key` (`spantrail_pro_monthly`,
`spantrail_team_monthly`) so re-running the setup reuses them instead of
creating duplicates.

## Webhook endpoint (created, test mode)

```
id      : we_1UVIacEg75dpvMZqhjPekswq
url     : https://spantrail.com/api/v1/billing/webhook
status  : enabled
events  : checkout.session.completed
          customer.subscription.updated
          customer.subscription.deleted
          invoice.payment_failed
```

The signing secret is stored in the server `.env` as `STRIPE_WEBHOOK_SECRET`.

**Delivery status: blocked on DNS.** `spantrail.com` has no A record yet, so
Stripe cannot reach the endpoint. Once the record is live and the ACME
cutover has run, deliveries will start working. Events emitted in the
meantime are queued by Stripe and retried.

## Known gap: the customer portal

`/api/v1/billing/portal` needs a **default billing portal configuration**.
Your account has none (count: 0), so that endpoint will fail until one
exists. Create it with:

```bash
ssh root@178.105.143.122
/opt/spantrail/venv/bin/python /opt/spantrail/app/stripe_portal.py
```

`stripe_portal.py` (in this repo) creates it with:
- subscription cancel (immediate)
- payment method update
- invoice history
- subscription update restricted to our two products

It also runs a real checkout-session smoke test and cleans up after itself.

## Verified working

| Check | Result |
|---|---|
| Key authentication | OK, account retrieved via `accounts.retrieve_current()` |
| Product + price creation | OK, both plans created in test mode |
| Webhook endpoint creation | OK, 4 events enabled |
| `.env` written | OK - 4 values, `chmod 0600`, owner `spantrail` |
| API restart | OK, `spantrail-api.service` active, `/health` 200 |
| Unsigned webhook | 400 (correctly rejected) |
| Checkout session creation | 200, returns a real `checkout.stripe.com` URL |
| Checkout with an unknown plan | 400 |
| Billing portal session | 503 `stripe_not_configured` -> now 400/500 until a portal config exists (see above) |

## Not yet done

1. **Billing portal configuration** - run `stripe_portal.py` (above).
2. **DNS + ACME cutover** - add the A record, then run `cutover.sh`.
3. **A real checkout** - with the domain live, buy a Pro plan with the test
   card `4242 4242 4242 4242` and confirm the tenant row flips to `plan=pro`.
4. **Cancellation test** - cancel in the Stripe test dashboard, confirm
   `status='cancelled'`.
5. **Live mode** - only after 3 and 4 pass. Create the products again in live
   mode (prices are mode-specific) and re-run `stripe_run.sh` with the live key.
