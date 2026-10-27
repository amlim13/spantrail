import os
import hashlib
import secrets
import uuid
import datetime as dt

import db

API_KEY_PREFIX = "spantrail_sk_"


def hash_key(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_key():
    return API_KEY_PREFIX + secrets.token_hex(24)


def create_tenant(name, email=None, plan="free"):
    raw = generate_key()
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO tenants (id, name, email, api_key_hash, status, plan, activated_at)
               VALUES (%s, %s, %s, %s, 'active', %s, now())
               RETURNING id, name, email, plan, status, created_at""",
            (str(uuid.uuid4()), name, email, hash_key(raw), plan),
        )
        row = cur.fetchone()
    return row, raw


def authenticate(raw_key):
    if not raw_key:
        return None
    h = hash_key(raw_key)
    with db.cursor() as cur:
        cur.execute(
            """SELECT id, name, email, plan, status, stripe_customer_id
               FROM tenants WHERE api_key_hash = %s""",
            (h,),
        )
        return cur.fetchone()


def rotate_key(tenant_id):
    raw = generate_key()
    with db.cursor() as cur:
        cur.execute(
            "UPDATE tenants SET api_key_hash = %s WHERE id = %s RETURNING id, name",
            (hash_key(raw), tenant_id),
        )
        row = cur.fetchone()
    return row, raw


def plan_for(tenant_id):
    with db.cursor() as cur:
        cur.execute("SELECT plan FROM tenants WHERE id = %s", (tenant_id,))
        r = cur.fetchone()
    return r["plan"] if r else "free"
