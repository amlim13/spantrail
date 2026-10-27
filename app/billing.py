"""Stripe billing helpers.

Uses the current stripe-python v16 client API (StripeClient + client.v1.*).
The legacy `stripe.api_key` global + `stripe.checkout.Session.create(...)`
style was deprecated in v13 and breaks in v15+, where StripeObject no longer
inherits from dict (so `.get()` is gone).

Safe no-op when STRIPE_SECRET_KEY is unset: every function returns
(None, error) instead of raising, so the API stays up without Stripe.
"""
import os
import stripe
from stripe import StripeClient

_client = None
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "") or None

PLANS = {
    "free": {"events": 50_000, "retention_days": 30, "usd": 0},
    "pro": {"events": 1_000_000, "retention_days": 30, "usd": 29},
    "team": {"events": 10_000_000, "retention_days": 90, "usd": 99},
}

PRICE_ENV = {
    "pro": "STRIPE_PRICE_PRO",
    "team": "STRIPE_PRICE_TEAM",
}

# Events we act on. Keep in sync with the Stripe dashboard webhook endpoint.
WEBHOOK_EVENTS = [
    "checkout.session.completed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.payment_failed",
]


def get_client():
    """Return a StripeClient, or None when Stripe is not configured."""
    global _client
    if _client is not None:
        return _client
    key = os.environ.get("STRIPE_SECRET_KEY", "") or ""
    if not key:
        return None
    _client = StripeClient(key, max_network_retries=3)
    return _client


def enabled():
    return get_client() is not None


def price_id_for(plan):
    env = PRICE_ENV.get(plan)
    if not env:
        return None
    return os.environ.get(env) or None


def _get(obj, key, default=None):
    """Read a key from a StripeObject or a plain dict."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return obj[key]
    except Exception:
        return default


def create_checkout_session(tenant_id, plan, email, success_url, cancel_url):
    """Create a subscription Checkout session. Returns (url, error)."""
    client = get_client()
    if client is None:
        return None, "stripe_not_configured"
    price = price_id_for(plan)
    if not price:
        return None, f"missing_price_id_for_{plan}"
    metadata = {"tenant_id": str(tenant_id), "plan": plan}
    try:
        session = client.v1.checkout.sessions.create(
            {
                "mode": "subscription",
                "customer_email": email or None,
                "line_items": [{"price": price, "quantity": 1}],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "client_reference_id": str(tenant_id),
                "metadata": metadata,
                "subscription_data": {"metadata": metadata},
            }
        )
    except Exception as e:  # network / auth / bad price
        return None, f"stripe_error: {e}"
    return _get(session, "url"), None


def create_portal_session(stripe_customer_id, return_url):
    """Create a customer-portal session for managing an existing subscription."""
    client = get_client()
    if client is None or not stripe_customer_id:
        return None, "stripe_not_configured"
    try:
        s = client.v1.billing_portal.sessions.create(
            {"customer": stripe_customer_id, "return_url": return_url}
        )
    except Exception as e:
        return None, f"stripe_error: {e}"
    return _get(s, "url"), None


def construct_event(payload, sig_header):
    """Verify and parse a webhook event. Returns (event_dict, error)."""
    client = get_client()
    if client is None:
        return None, "stripe_not_configured"
    if not WEBHOOK_SECRET:
        return None, "webhook_secret_not_configured"
    try:
        event = client.construct_event(payload, sig_header, WEBHOOK_SECRET)
    except Exception as e:
        return None, str(e)
    # StripeObject no longer subclasses dict in v15+; to_dict() gives plain data.
    if hasattr(event, "to_dict"):
        event = event.to_dict()
    return event, None
