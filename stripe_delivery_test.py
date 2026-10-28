"""Trigger customer.subscription.updated - one of OUR four subscribed events -
and verify Stripe delivers it to our public endpoint and our server handles it.
"""
import os
import time
import subprocess

for line in open("/opt/spantrail/app/.env"):
    line = line.strip()
    if line.startswith("STRIPE_SECRET_KEY="):
        os.environ["STRIPE_SECRET_KEY"] = line.split("=", 1)[1]

from stripe import StripeClient

c = StripeClient(os.environ["STRIPE_SECRET_KEY"])
# The tenant to attribute the test subscription to. Override with
# SPANTRAIL_TENANT_ID=... .
TID = os.environ.get("SPANTRAIL_TENANT_ID", "05b5dfb0-40f3-4f3c-86cf-692696861858")


def webhook_log(n=80):
    log = subprocess.run(
        ["journalctl", "-u", "spantrail-api", "-n", str(n), "--no-pager"],
        capture_output=True, text=True, timeout=30).stdout
    return [l.strip() for l in log.splitlines() if "billing/webhook" in l]


def external_only(lines):
    """Webhook deliveries that did not come from localhost or our own IP."""
    mine = os.environ.get("SPANTRAIL_VPS_IP", "178.105.143.122")
    return [l for l in lines if "127.0.0.1" not in l and mine not in l]


print("=== 1. customer + attached test card ===")
cust = c.v1.customers.create(
    {"email": "upd.test@spantrail.com", "metadata": {"app": "spantrail", "test": "upd"}}
).to_dict()
pm = c.v1.payment_methods.create(
    {"type": "card", "card": {"token": "tok_visa"},
     "billing_details": {"email": "upd.test@spantrail.com"}}
).to_dict()
c.v1.payment_methods.attach(pm["id"], {"customer": cust["id"]})
print("  customer: %s   pm: %s" % (cust.get("id"), pm.get("id")))

price_id = None
for line in open("/opt/spantrail/app/.env"):
    if line.startswith("STRIPE_PRICE_PRO="):
        price_id = line.split("=", 1)[1].strip()

print()
print("=== 2. subscription (incomplete) ===")
sub = c.v1.subscriptions.create(
    {
        "customer": cust["id"],
        "items": [{"price": price_id, "quantity": 1}],
        "default_payment_method": pm.get("id"),
        "metadata": {"tenant_id": TID, "plan": "pro"},
        "payment_behavior": "default_incomplete",
        "payment_settings": {"save_default_payment_method": "on_subscription"},
        "expand": ["latest_invoice.payment_intent"],
    }
).to_dict()
sid = sub["id"]
print("  %s status=%s" % (sid, sub.get("status")))

print()
print("=== 3. confirm the payment intent -> subscription activates ===")
pi = ((sub.get("latest_invoice") or {}).get("payment_intent")) or {}
pi_id = pi.get("id") if isinstance(pi, dict) else pi
print("  payment_intent: %s status=%s" % (pi_id, pi.get("status") if isinstance(pi, dict) else "?"))
if pi_id:
    confirmed = c.v1.payment_intents.confirm(pi_id, {"payment_method": pm["id"]}).to_dict()
    print("  pi status: %s" % confirmed.get("status"))

time.sleep(3)
sub = c.v1.subscriptions.retrieve(sid).to_dict()
print("  subscription status now: %s" % sub.get("status"))

print()
print("=== 4. update the subscription -> fires customer.subscription.updated ===")
upd = c.v1.subscriptions.update(
    sid, {"metadata": {"tenant_id": TID, "plan": "pro", "test": "upd"}}
).to_dict()
print("  updated, status=%s" % upd.get("status"))

print()
print("=== 5. wait for the delivery ===")
found = None
for i in range(15):
    time.sleep(4)
    ext = external_only(webhook_log(80))
    if ext:
        found = ext
        print("  DELIVERED after ~%ds" % ((i + 1) * 4))
        for l in ext[-4:]:
            print("    " + (l.split("] ", 1)[-1] if "] " in l else l))
        break
    print("  waiting (%ds)..." % ((i + 1) * 4))

if not found:
    print("  no external delivery. Recent webhook lines:")
    for l in webhook_log(8):
        print("    " + (l.split("] ", 1)[-1] if "] " in l else l))
    print()
    print("  what Stripe thinks of the events:")
    evs = c.v1.events.list({"limit": 12}).to_dict()
    for e in evs.get("data", [])[:10]:
        whs = e.get("webhooks") or []
        print("    %-36s %-34s %s" % (
            e.get("type"), e.get("id"),
            ",".join("%s %s" % (w.get("status"), (w.get("url") or "")[:40]) for w in whs) or "(none)"))

print()
print("=== 6. the tenant row ===")
out = subprocess.run(
    ["sudo", "-u", "spantrail", "/usr/lib/postgresql/16/bin/psql",
     "-h", "/opt/spantrail/pgdata", "-U", "spantrail", "-d", "spantrail", "-tAc",
     "SELECT name, plan, status, coalesce(stripe_customer_id,'(none)'), "
     "coalesce(stripe_subscription_id,'(none)') FROM tenants"],
    capture_output=True, text=True, timeout=30).stdout
print("  " + out.strip())

print()
print("=== 7. cleanup ===")
try:
    c.v1.subscriptions.cancel(sid)
    print("  subscription cancelled")
except Exception as e:
    print("  cancel: %s" % e)
try:
    c.v1.customers.delete(cust["id"])
    print("  customer deleted")
except Exception as e:
    print("  customer delete: %s" % e)
