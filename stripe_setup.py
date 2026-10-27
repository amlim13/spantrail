#!/usr/bin/env python3
"""Provision SpanTrail's Stripe configuration over the Stripe API.

Run ON THE SERVER as root:

    /opt/spantrail/venv/bin/python /opt/spantrail/app/stripe_setup.py

It prompts for the Stripe secret key in a hidden field (getpass), so the key
never appears in the terminal, in shell history, or in this conversation.

Then it, over the API:
  1. Verifies the key and reports the account
  2. Creates (or reuses) the two products and their monthly prices
  3. Creates (or reuses) the webhook endpoint and captures its signing secret
  4. Writes STRIPE_SECRET_KEY / STRIPE_PRICE_PRO / STRIPE_PRICE_TEAM /
     STRIPE_WEBHOOK_SECRET into /opt/spantrail/app/.env  (chmod 0600)
  5. Restarts the API and verifies the endpoints respond

Idempotent: re-running it reuses existing objects by lookup_key / name.
"""
import getpass
import json
import os
import re
import subprocess
import sys

APP = "/opt/spantrail"
ENV_FILE = f"{APP}/app/.env"

PLANS = [
    # (plan key, product name, description, amount in cents, lookup_key)
    ("pro", "SpanTrail Pro",
     "1M events per month, 30-day retention, cost dashboards, email support.",
     2900, "spantrail_pro_monthly"),
    ("team", "SpanTrail Team",
     "10M events per month, 90-day retention, shared workspaces, priority support.",
     9900, "spantrail_team_monthly"),
]

WEBHOOK_EVENTS = [
    "checkout.session.completed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.payment_failed",
]

WEBHOOK_URL = os.environ.get("SPANTRAIL_WEBHOOK_URL", "https://spantrail.com/api/v1/billing/webhook")
WEBHOOK_DESC = "SpanTrail billing"

# Set with --skip-webhook to create the products and prices first, then the
# webhook endpoint in a second pass once the domain resolves.
SKIP_WEBHOOK = False
SKIP_WEBHOOK_RESULT = None


def die(msg, code=1):
    print(f"\nERROR: {msg}\n", file=sys.stderr)
    sys.exit(code)


def ok(msg):
    print(f"  [ok] {msg}")


def info(msg):
    print(f"       {msg}")


def hr(title):
    print(f"\n=== {title} ===")


def getpass_stripe_key():
    """Read the secret key without echoing it."""
    print("\nStripe secret key (input is hidden).")
    print("  - Test mode: starts with sk_test_")
    print("  - Live mode:  starts with sk_live_")
    key = getpass.getpass("Paste the secret key: ").strip()
    if not key:
        die("no key entered")
    if not re.match(r"^sk_(test|live)_[A-Za-z0-9_]{8,}$", key):
        die("that does not look like a Stripe secret key (expected sk_test_... or sk_live_...)")
    return key


def client_for(key):
    from stripe import StripeClient

    return StripeClient(key, max_network_retries=3)


def check_account(client):
    hr("1. Verify the key")
    # With a secret key the account is implicit, but accounts.retrieve()
    # still requires an id. Retrieve the account the key belongs to.
    try:
        accounts = client.v1.accounts.list({"limit": 1})
        alist = accounts.to_dict() if hasattr(accounts, "to_dict") else dict(accounts)
        rows = alist.get("data") or []
        if not rows:
            die("the key authenticated but no account was returned")
        acct_id = rows[0]["id"]
        acct = client.v1.accounts.retrieve(acct_id)
    except Exception as e:
        die(f"the key was rejected by Stripe: {e}")
    data = acct.to_dict() if hasattr(acct, "to_dict") else dict(acct)
    livemode = data.get("livemode")
    info(f"account id     : {data.get('id')}")
    info(f"business name  : {data.get('business_name') or data.get('settings', {}).get('dashboard', {}).get('display_name') or '(not set)'}")
    info(f"country        : {data.get('country')}")
    info(f"default currency: {data.get('default_currency')}")
    info(f"MODE           : {'LIVE' if livemode else 'TEST'}")
    if livemode:
        print("\n  *** This is a LIVE key. Live-mode objects and real charges. ***")
    else:
        info("test mode - no real charges will be made")
    return livemode


def find_price_by_lookup_key(client, lookup_key):
    try:
        prices = client.v1.prices.list({"lookup_keys": [lookup_key], "active": True, "limit": 1})
    except Exception:
        return None
    data = prices.to_dict() if hasattr(prices, "to_dict") else dict(prices)
    items = data.get("data") or []
    return items[0] if items else None


def find_product_by_name(client, name):
    try:
        products = client.v1.products.list({"active": True, "limit": 100})
    except Exception:
        return None
    data = products.to_dict() if hasattr(products, "to_dict") else dict(products)
    for p in data.get("data") or []:
        if (p.get("name") or "").lower() == name.lower():
            return p
    return None


def ensure_price(client, plan, name, description, amount_cents, lookup_key):
    existing = find_price_by_lookup_key(client, lookup_key)
    if existing:
        ok(f"{name}: price {existing['id']} already exists (reused)")
        info(f"  {existing.get('unit_amount', 0) / 100:.2f} {existing.get('currency', '').upper()} / {existing.get('recurring', {}).get('interval', '?')}")
        return existing["id"], existing.get("product")

    prod = find_product_by_name(client, name)
    if prod:
        ok(f"{name}: product {prod['id']} found")
    else:
        try:
            created = client.v1.products.create(
                {
                    "name": name,
                    "description": description,
                    "metadata": {"plan": plan, "app": "spantrail"},
                }
            )
        except Exception as e:
            die(f"could not create the {name} product: {e}")
        prod = created.to_dict() if hasattr(created, "to_dict") else dict(created)
        ok(f"{name}: product {prod['id']} created")

    try:
        created_price = client.v1.prices.create(
            {
                "product": prod["id"],
                "unit_amount": amount_cents,
                "currency": "usd",
                "recurring": {"interval": "month"},
                "lookup_key": lookup_key,
                "metadata": {"plan": plan, "app": "spantrail"},
            }
        )
    except Exception as e:
        die(f"could not create the {name} price: {e}")
    price = created_price.to_dict() if hasattr(created_price, "to_dict") else dict(created_price)
    ok(f"{name}: price {price['id']} created (${amount_cents / 100:.2f}/mo)")
    return price["id"], prod["id"]


def ensure_webhook(client):
    hr("3. Webhook endpoint")
    try:
        eps = client.v1.webhook_endpoints.list({"limit": 100})
    except Exception as e:
        die(f"could not list webhook endpoints: {e}")
    data = eps.to_dict() if hasattr(eps, "to_dict") else dict(eps)
    for ep in data.get("data") or []:
        if ep.get("url") == WEBHOOK_URL:
            ok(f"webhook endpoint {ep['id']} already exists (reused)")
            secret = ep.get("secret")
            if not secret:
                info("  the signing secret is not returned on list; deleting and recreating")
                try:
                    client.v1.webhook_endpoints.delete(ep["id"])
                except Exception as e:
                    die(f"could not delete the stale webhook endpoint: {e}")
                return _create_webhook(client)
            info(f"  secret: {secret[:12]}... (stored)")
            return ep["id"], secret

    return _create_webhook(client)


def _create_webhook(client):
    try:
        created = client.v1.webhook_endpoints.create(
            {
                "url": WEBHOOK_URL,
                "enabled_events": WEBHOOK_EVENTS,
                "description": WEBHOOK_DESC,
                "metadata": {"app": "spantrail"},
            }
        )
    except Exception as e:
        die(
            f"could not create the webhook endpoint at {WEBHOOK_URL}:\n  {e}\n"
            "  Stripe may have refused the URL. If the domain does not resolve yet,\n"
            "  run this again after the DNS A record is live."
        )
    ep = created.to_dict() if hasattr(created, "to_dict") else dict(created)
    ok(f"webhook endpoint {ep['id']} created")
    info(f"  url   : {ep.get('url')}")
    info(f"  events: {', '.join(ep.get('enabled_events', []))}")
    secret = ep.get("secret")
    if not secret:
        die("Stripe did not return a signing secret for the new endpoint")
    return ep["id"], secret


def write_env(values):
    hr("4. Write the .env")
    if not os.path.exists(ENV_FILE):
        die(f"{ENV_FILE} does not exist")
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    out = []
    seen = set()
    for line in lines:
        m = re.match(r"^([A-Z_]+)=", line)
        if m and m.group(1) in values:
            out.append(f"{m.group(1)}={values[m.group(1)]}")
            seen.add(m.group(1))
        else:
            out.append(line)
    for k, v in values.items():
        if k not in seen:
            out.append(f"{k}={v}")

    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    os.chmod(ENV_FILE, 0o600)
    subprocess.run(["chown", "spantrail:spantrail", ENV_FILE], check=False)
    for k in values:
        ok(f"{k} written")


def main():
    global SKIP_WEBHOOK
    print("SpanTrail Stripe setup")
    print("=" * 60)
    if "--skip-webhook" in sys.argv:
        SKIP_WEBHOOK = True
        print("(products and prices only; the webhook endpoint will be created in a second run)")
    key = getpass_stripe_key()

    try:
        from stripe import StripeClient  # noqa: F401
    except Exception as e:
        die(f"stripe-python is not importable: {e}")

    client = client_for(key)
    livemode = check_account(client)

    hr("2. Products and prices")
    env = {"STRIPE_SECRET_KEY": key}
    for plan, name, desc, amount, lookup in PLANS:
        price_id, _prod_id = ensure_price(client, plan, name, desc, amount, lookup)
        env["STRIPE_PRICE_PRO" if plan == "pro" else "STRIPE_PRICE_TEAM"] = price_id

    hr("3. Webhook endpoint")
    ep_id = secret = None
    if SKIP_WEBHOOK:
        info("skipped (--skip-webhook)")
    else:
        try:
            ep_id, secret = ensure_webhook(client)
            env["STRIPE_WEBHOOK_SECRET"] = secret
        except SystemExit:
            # The products and the secret key are still worth writing. Report
            # the webhook failure at the end rather than aborting everything.
            info("the webhook endpoint could not be created; continuing")
            info("re-run this script once the domain resolves to finish it")
            SKIP_WEBHOOK_RESULT = "FAILED"

    write_env(env)

    hr("5. Restart and verify")
    subprocess.run(["systemctl", "restart", "spantrail-api.service"], check=False)
    import time

    time.sleep(5)
    st = subprocess.run(["systemctl", "is-active", "spantrail-api.service"],
                        capture_output=True, text=True)
    info(f"spantrail-api.service: {st.stdout.strip()}")

    import urllib.request
    import ssl

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    for label, url in [
        ("health", "https://127.0.0.1:8443/health"),
        ("webhook (no signature -> 400 is correct)", "https://127.0.0.1:8443/api/v1/billing/webhook"),
    ]:
        if "webhook" in url:
            req = urllib.request.Request(url, data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json"})
        else:
            req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
                info(f"{label}: HTTP {r.status}")
        except urllib.error.HTTPError as e:
            info(f"{label}: HTTP {e.code}")
        except Exception as e:
            info(f"{label}: error {e}")

    hr("6. Account state")
    try:
        subs = client.v1.subscriptions.list({"limit": 5, "status": "all"})
        sd = subs.to_dict() if hasattr(subs, "to_dict") else dict(subs)
        n = len(sd.get("data") or [])
        info(f"subscriptions on this account: {n}")
    except Exception as e:
        info(f"(could not list subscriptions: {e})")

    print("\n" + "=" * 60)
    if livemode:
        print("SETUP COMPLETE - LIVE MODE. Verify a real checkout before selling.")
    else:
        print("SETUP COMPLETE - TEST MODE.")
    print(f"  products + prices: done")
    if ep_id:
        print(f"  webhook endpoint : {WEBHOOK_URL}")
        print(f"  endpoint id      : {ep_id}")
        print("  signing secret   : written to the .env (not printed)")
    else:
        print(f"  webhook endpoint : NOT created yet")
        print(f"                     expected at {WEBHOOK_URL}")
        print("                     re-run this script once the A record is live")
    print("")
    print("Next: test a checkout.")
    print(f"  curl -X POST {WEBHOOK_URL.replace('/webhook','')}/checkout \\")
    print("    -H 'X-API-Key: <your key>' -H 'Content-Type: application/json' \\")
    print("    -d '{\"plan\":\"pro\"}'")
    print("  Then open the returned checkout.stripe.com URL and use card 4242 4242 4242 4242.")


if __name__ == "__main__":
    main()
