"""Configure the Stripe billing portal and verify a real checkout session.

Reads the key from the .env; never prints it.
"""
import os
import json

for line in open("/opt/spantrail/app/.env"):
    line = line.strip()
    if line.startswith("STRIPE_SECRET_KEY="):
        os.environ["STRIPE_SECRET_KEY"] = line.split("=", 1)[1]

from stripe import StripeClient

c = StripeClient(os.environ["STRIPE_SECRET_KEY"])

print("=== 1. BILLING PORTAL CONFIGURATION ===")
cfg = c.v1.billing_portal.configurations.list({"limit": 5}).to_dict()
items = cfg.get("data", [])
print("  existing: %d" % len(items))

default = None
for cc in items:
    print("    %s default=%s" % (cc.get("id"), cc.get("is_default")))
    if cc.get("is_default"):
        default = cc

if not default:
    print("  creating a default configuration...")
    # subscription_update.products is a list of {product, prices} objects,
    # not a flat list of ids. Group our prices by their product.
    env = {}
    for line in open("/opt/spantrail/app/.env"):
        for k in ("STRIPE_PRICE_PRO", "STRIPE_PRICE_TEAM"):
            if line.startswith(k + "="):
                env[k] = line.split("=", 1)[1].strip()

    by_product = {}
    for key, price_id in env.items():
        pr = c.v1.prices.retrieve(price_id).to_dict()
        prod = pr.get("product")
        by_product.setdefault(prod, []).append(price_id)
        print("    %-22s -> %s (price %s)" % (key, prod, price_id))

    features = {
        "subscription_cancel": {"enabled": True, "mode": "immediately"},
        "payment_method_update": {"enabled": True},
        "invoice_history": {"enabled": True},
    }
    if by_product:
        features["subscription_update"] = {
            "enabled": True,
            "default_allowed_updates": ["price"],
            "products": [
                {"product": prod, "prices": prices}
                for prod, prices in by_product.items()
            ],
        }
        print("    products: %s" % ", ".join(by_product.keys()))

    created = c.v1.billing_portal.configurations.create(
        {
            "business_profile": {
                "headline": "Manage your SpanTrail subscription",
                "privacy_policy_url": "https://spantrail.com/privacy",
                "terms_of_service_url": "https://spantrail.com/terms",
            },
            "features": features,
            "metadata": {"app": "spantrail"},
        }
    )
    data = created.to_dict()
    print("  created %s (default=%s)" % (data.get("id"), data.get("is_default")))
else:
    print("  a default configuration already exists - nothing to do")

print()
print("=== 2. A REAL CHECKOUT SESSION (the full path) ===")
# Create a customer so the session has a real email on it.
cust = c.v1.customers.create(
    {"email": "smoke@test.local", "metadata": {"app": "spantrail", "test": "1"}}
).to_dict()
print("  customer %s" % cust.get("id"))

price_id = None
for line in open("/opt/spantrail/app/.env"):
    if line.startswith("STRIPE_PRICE_PRO="):
        price_id = line.split("=", 1)[1].strip()
print("  price   %s" % price_id)

session = c.v1.checkout.sessions.create(
    {
        "mode": "subscription",
        "customer": cust["id"],
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": "https://spantrail.com/dashboard?checkout=success",
        "cancel_url": "https://spantrail.com/dashboard?checkout=cancelled",
        "client_reference_id": "smoke-test-tenant",
        "metadata": {"tenant_id": "smoke-test-tenant", "plan": "pro"},
        "subscription_data": {"metadata": {"tenant_id": "smoke-test-tenant", "plan": "pro"}},
    }
).to_dict()
print("  session %s" % session.get("id"))
print("  status  %s" % session.get("status"))
print("  url     %s" % (session.get("url") or "")[:80])
print("  amount  %s %s" % (session.get("amount_total"), session.get("currency")))
print("  mode    %s" % session.get("mode"))

# Read it back through the API to be sure it is a valid, live session.
fetched = c.v1.checkout.sessions.retrieve(session["id"]).to_dict()
print("  retrieved status: %s" % fetched.get("status"))
print("  payment_status:  %s" % fetched.get("payment_status"))
print("  has url:         %s" % bool(fetched.get("url")))

print()
print("=== 3. clean up the smoke-test objects ===")
try:
    c.v1.checkout.sessions.expire(session["id"])
    print("  checkout session expired")
except Exception as e:
    print("  expire: %s" % e)
try:
    c.v1.customers.delete(cust["id"])
    print("  customer deleted")
except Exception as e:
    print("  customer delete: %s" % e)

print()
print("=== 4. how many objects did we leave on the account? ===")
prods = c.v1.products.list({"limit": 20}).to_dict()
print("  products: %d" % len(prods.get("data", [])))
prices = c.v1.prices.list({"limit": 20}).to_dict()
print("  prices:   %d" % len(prices.get("data", [])))
eps = c.v1.webhook_endpoints.list({"limit": 20}).to_dict()
print("  webhooks: %d" % len(eps.get("data", [])))
