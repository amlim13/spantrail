"""SpanTrail API - agent observability ingest + read API."""
import os
import json
import uuid
import datetime as dt
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from psycopg2.extras import execute_values

import db
import auth
import billing

VERSION = "0.1.0"
RETENTION_DAYS = 30

app = FastAPI(title="SpanTrail", version=VERSION, docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    db.apply_schema()


# ---------------------------------------------------------------- models

class SpanIn(BaseModel):
    id: Optional[str] = None
    trace_id: str
    parent_id: Optional[str] = None
    name: str
    kind: str = "step"
    started_at: Optional[dt.datetime] = None
    ended_at: Optional[dt.datetime] = None
    duration_ms: Optional[float] = None
    input: Optional[Dict[str, Any]] = None
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    model: Optional[str] = None
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    cost_usd: Optional[float] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class LogIn(BaseModel):
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    level: str = "info"
    message: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class TraceIn(BaseModel):
    id: Optional[str] = None
    name: str
    session_id: Optional[str] = None
    started_at: Optional[dt.datetime] = None
    ended_at: Optional[dt.datetime] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class IngestBatch(BaseModel):
    traces: List[TraceIn] = Field(default_factory=list)
    spans: List[SpanIn] = Field(default_factory=list)
    logs: List[LogIn] = Field(default_factory=list)


# ---------------------------------------------------------------- auth

def require_tenant(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
):
    key = x_api_key
    if not key and authorization and authorization.lower().startswith("bearer "):
        key = authorization[7:].strip()
    tenant = auth.authenticate(key)
    if not tenant:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    if tenant["status"] != "active":
        raise HTTPException(status_code=403, detail="tenant not active")
    return tenant


def require_admin(x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token")):
    expected = os.environ.get("ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="admin token not configured")
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=403, detail="forbidden")
    return True


# ---------------------------------------------------------------- health

@app.get("/health")
def health():
    try:
        db.health()
        return {"status": "ok", "version": VERSION, "db": "ok"}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "degraded", "db": str(e)})


@app.get("/api/v1/health")
def health_api():
    return health()


# ---------------------------------------------------------------- ingest

@app.post("/api/v1/ingest")
def ingest(batch: IngestBatch, tenant=Depends(require_tenant)):
    tid = tenant["id"]
    now = dt.datetime.now(dt.timezone.utc)

    trace_rows = []
    for t in batch.traces:
        trace_rows.append(
            (
                t.id or str(uuid.uuid4()),
                tid,
                t.name,
                t.session_id,
                t.started_at or now,
                t.ended_at,
                json.dumps(t.meta or {}),
            )
        )

    span_rows = []
    for s in batch.spans:
        span_rows.append(
            (
                s.id or str(uuid.uuid4()),
                tid,
                s.trace_id,
                s.parent_id,
                s.name,
                s.kind,
                s.started_at or now,
                s.ended_at,
                s.duration_ms,
                json.dumps(s.input) if s.input is not None else None,
                json.dumps(s.output) if s.output is not None else None,
                s.error,
                s.model,
                s.tokens_input,
                s.tokens_output,
                s.cost_usd,
                json.dumps(s.meta or {}),
            )
        )

    log_rows = []
    for l in batch.logs:
        log_rows.append((tid, l.trace_id, l.span_id, l.level, l.message, json.dumps(l.meta or {})))

    with db.conn() as c:
        with c.cursor() as cur:
            if trace_rows:
                execute_values(
                    cur,
                    """INSERT INTO traces (id, tenant_id, name, session_id, started_at, ended_at, meta)
                       VALUES %s ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name,
                       ended_at = EXCLUDED.ended_at, meta = EXCLUDED.meta""",
                    trace_rows,
                )
            if span_rows:
                execute_values(
                    cur,
                    """INSERT INTO spans (id, tenant_id, trace_id, parent_id, name, kind, started_at,
                       ended_at, duration_ms, input, output, error, model, tokens_input,
                       tokens_output, cost_usd, meta)
                       VALUES %s ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name,
                       ended_at = EXCLUDED.ended_at, duration_ms = EXCLUDED.duration_ms,
                       output = EXCLUDED.output, error = EXCLUDED.error""",
                    span_rows,
                )
            if log_rows:
                execute_values(
                    cur,
                    """INSERT INTO logs (tenant_id, trace_id, span_id, level, message, meta)
                       VALUES %s""",
                    log_rows,
                )

    return {
        "ok": True,
        "accepted": {
            "traces": len(trace_rows),
            "spans": len(span_rows),
            "logs": len(log_rows),
        },
    }


# ---------------------------------------------------------------- read

@app.get("/api/v1/traces")
def list_traces(
    limit: int = Query(50, le=500),
    offset: int = Query(0, ge=0),
    q: Optional[str] = None,
    tenant=Depends(require_tenant),
):
    with db.cursor() as cur:
        if q:
            cur.execute(
                """SELECT t.id, t.name, t.session_id, t.started_at, t.ended_at,
                          COUNT(s.id) AS span_count,
                          COUNT(s.id) FILTER (WHERE s.error IS NOT NULL) AS error_count,
                          COALESCE(SUM(s.tokens_input),0) AS tokens_in,
                          COALESCE(SUM(s.tokens_output),0) AS tokens_out,
                          COALESCE(SUM(s.cost_usd),0) AS cost_usd
                   FROM traces t LEFT JOIN spans s ON s.trace_id = t.id
                   WHERE t.tenant_id = %s AND t.name ILIKE %s
                   GROUP BY t.id ORDER BY t.started_at DESC LIMIT %s OFFSET %s""",
                (tenant["id"], f"%{q}%", limit, offset),
            )
        else:
            cur.execute(
                """SELECT t.id, t.name, t.session_id, t.started_at, t.ended_at,
                          COUNT(s.id) AS span_count,
                          COUNT(s.id) FILTER (WHERE s.error IS NOT NULL) AS error_count,
                          COALESCE(SUM(s.tokens_input),0) AS tokens_in,
                          COALESCE(SUM(s.tokens_output),0) AS tokens_out,
                          COALESCE(SUM(s.cost_usd),0) AS cost_usd
                   FROM traces t LEFT JOIN spans s ON s.trace_id = t.id
                   WHERE t.tenant_id = %s
                   GROUP BY t.id ORDER BY t.started_at DESC LIMIT %s OFFSET %s""",
                (tenant["id"], limit, offset),
            )
        rows = [dict(r) for r in cur.fetchall()]
    return {"traces": rows, "count": len(rows), "limit": limit, "offset": offset}


@app.get("/api/v1/traces/{trace_id}")
def get_trace(trace_id: str, tenant=Depends(require_tenant)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT * FROM traces WHERE id = %s AND tenant_id = %s", (trace_id, tenant["id"])
        )
        t = cur.fetchone()
        if not t:
            raise HTTPException(status_code=404, detail="trace not found")
        cur.execute(
            """SELECT * FROM spans WHERE trace_id = %s AND tenant_id = %s
               ORDER BY started_at ASC, duration_ms DESC NULLS LAST""",
            (trace_id, tenant["id"]),
        )
        spans = [dict(r) for r in cur.fetchall()]
        cur.execute(
            """SELECT * FROM logs WHERE trace_id = %s AND tenant_id = %s
               ORDER BY created_at ASC LIMIT 500""",
            (trace_id, tenant["id"]),
        )
        logs = [dict(r) for r in cur.fetchall()]
    return {"trace": dict(t), "spans": spans, "logs": logs}


@app.get("/api/v1/spans")
def list_spans(
    limit: int = Query(100, le=1000),
    kind: Optional[str] = None,
    errored: Optional[bool] = None,
    tenant=Depends(require_tenant),
):
    where = ["tenant_id = %s"]
    args = [tenant["id"]]
    if kind:
        where.append("kind = %s")
        args.append(kind)
    if errored is not None:
        where.append("error IS NOT NULL" if errored else "error IS NULL")
    args.append(limit)
    with db.cursor() as cur:
        cur.execute(
            f"""SELECT id, trace_id, parent_id, name, kind, started_at, ended_at,
                       duration_ms, error, model, tokens_input, tokens_output, cost_usd
                FROM spans WHERE {' AND '.join(where)}
                ORDER BY started_at DESC LIMIT %s""",
            tuple(args),
        )
        rows = [dict(r) for r in cur.fetchall()]
    return {"spans": rows, "count": len(rows)}


@app.get("/api/v1/stats")
def stats(tenant=Depends(require_tenant)):
    tid = tenant["id"]
    with db.cursor() as cur:
        cur.execute(
            """SELECT
                 COUNT(*) FILTER (WHERE created_at > now() - interval '24 hours') AS spans_24h,
                 COUNT(*) FILTER (WHERE created_at > now() - interval '7 days')  AS spans_7d,
                 COUNT(*) FILTER (WHERE error IS NOT NULL AND created_at > now() - interval '24 hours') AS errors_24h,
                 COALESCE(SUM(tokens_input)  FILTER (WHERE created_at > now() - interval '24 hours'),0) AS tokens_in_24h,
                 COALESCE(SUM(tokens_output) FILTER (WHERE created_at > now() - interval '24 hours'),0) AS tokens_out_24h,
                 COALESCE(SUM(cost_usd)    FILTER (WHERE created_at > now() - interval '24 hours'),0) AS cost_24h,
                 COALESCE(SUM(cost_usd)    FILTER (WHERE created_at > now() - interval '30 days'),0) AS cost_30d,
                 COALESCE(SUM(tokens_input + tokens_output) FILTER (WHERE created_at > now() - interval '30 days'),0) AS tokens_30d
               FROM spans WHERE tenant_id = %s""",
            (tid,),
        )
        s = dict(cur.fetchone())
        cur.execute(
            """SELECT percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms) AS p50,
                      percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95,
                      percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ms) AS p99
               FROM spans WHERE tenant_id = %s AND created_at > now() - interval '24 hours'
               AND duration_ms IS NOT NULL""",
            (tid,),
        )
        p = cur.fetchone()
        cur.execute(
            """SELECT kind, COUNT(*) AS n, AVG(duration_ms) AS avg_ms
               FROM spans WHERE tenant_id = %s AND created_at > now() - interval '7 days'
               GROUP BY kind ORDER BY n DESC""",
            (tid,),
        )
        kinds = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT COUNT(*) AS n FROM traces WHERE tenant_id = %s", (tid,)
        )
        tcount = cur.fetchone()["n"]
    out = dict(s)
    out.update({"p50_ms": p["p50"], "p95_ms": p["p95"], "p99_ms": p["p99"]})
    out.update({"by_kind": kinds, "traces_total": tcount})
    return out


@app.get("/api/v1/usage")
def usage(tenant=Depends(require_tenant)):
    plan = tenant["plan"] or "free"
    limits = billing.PLANS.get(plan, billing.PLANS["free"])
    with db.cursor() as cur:
        cur.execute(
            """SELECT COALESCE(SUM(tokens_input + tokens_output),0) AS events,
                      COALESCE(SUM(cost_usd),0) AS cost_usd
               FROM spans WHERE tenant_id = %s AND created_at > date_trunc('month', now())""",
            (tenant["id"],),
        )
        u = cur.fetchone()
    return {
        "plan": plan,
        "events_used": int(u["events"]),
        "events_limit": limits["events"],
        "cost_usd_month": float(u["cost_usd"] or 0),
        "retention_days": limits["retention_days"],
    }


# ---------------------------------------------------------------- admin

@app.post("/api/v1/admin/tenants")
def admin_create_tenant(payload: dict, _=Depends(require_admin)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    row, raw = auth.create_tenant(name, payload.get("email"), payload.get("plan", "free"))
    d = dict(row)
    d["api_key"] = raw
    return d


@app.get("/api/v1/admin/tenants")
def admin_list_tenants(_=Depends(require_admin)):
    with db.cursor() as cur:
        cur.execute(
            """SELECT id, name, email, plan, status, created_at, activated_at
               FROM tenants ORDER BY created_at DESC LIMIT 200"""
        )
        return {"tenants": [dict(r) for r in cur.fetchall()]}


@app.post("/api/v1/admin/tenants/{tenant_id}/rotate-key")
def admin_rotate(tenant_id: str, _=Depends(require_admin)):
    row, raw = auth.rotate_key(tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail="tenant not found")
    d = dict(row)
    d["api_key"] = raw
    return d


# ---------------------------------------------------------------- billing

@app.post("/api/v1/billing/checkout")
def checkout(payload: dict, tenant=Depends(require_tenant)):
    plan = payload.get("plan", "pro")
    if plan not in billing.PLANS:
        raise HTTPException(status_code=400, detail="unknown plan")
    base = os.environ.get("PUBLIC_URL", "").rstrip("/")
    url, err = billing.create_checkout_session(
        tenant["id"],
        plan,
        tenant.get("email"),
        f"{base}/dashboard?checkout=success",
        f"{base}/dashboard?checkout=cancelled",
    )
    if err:
        raise HTTPException(status_code=503, detail=err)
    return {"url": url}


@app.post("/api/v1/billing/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    event, err = billing.construct_event(payload, sig)
    if err:
        raise HTTPException(status_code=400, detail=f"webhook error: {err}")

    etype = event["type"]
    obj = event["data"]["object"]

    # StripeObject no longer subclasses dict in stripe-python v15+, but
    # billing.construct_event() calls to_dict(), which returns plain dicts
    # recursively. Guard anyway so a shape change cannot 500 the endpoint.
    if not isinstance(obj, dict):
        obj = dict(obj)

    with db.cursor() as cur:
        if etype == "checkout.session.completed":
            meta = obj.get("metadata") or {}
            tid = meta.get("tenant_id") or obj.get("client_reference_id")
            plan = meta.get("plan", "pro")
            if tid:
                cur.execute(
                    """UPDATE tenants SET status='active', plan=%s,
                       stripe_customer_id=%s, stripe_subscription_id=%s, activated_at=now()
                       WHERE id=%s""",
                    (plan, obj.get("customer"), obj.get("subscription"), tid),
                )
        elif etype in ("customer.subscription.updated", "customer.subscription.deleted"):
            meta = obj.get("metadata") or {}
            tid = meta.get("tenant_id")
            status = obj.get("status")
            if tid:
                if etype.endswith("deleted") or status in ("canceled", "unpaid"):
                    cur.execute(
                        "UPDATE tenants SET status='cancelled' WHERE id=%s", (tid,)
                    )
                else:
                    plan = meta.get("plan") or "pro"
                    cur.execute(
                        """UPDATE tenants SET status='active', plan=%s,
                           stripe_customer_id=%s, stripe_subscription_id=%s WHERE id=%s""",
                        (plan, obj.get("customer"), obj.get("id"), tid),
                    )
        elif etype == "invoice.payment_failed":
            cid = obj.get("customer")
            if cid:
                cur.execute(
                    "UPDATE tenants SET status='past_due' WHERE stripe_customer_id=%s", (cid,)
                )
    return {"received": True}


@app.post("/api/v1/billing/portal")
def billing_portal(tenant=Depends(require_tenant)):
    """Create a Stripe customer-portal session for managing the subscription."""
    base = os.environ.get("PUBLIC_URL", "").rstrip("/")
    url, err = billing.create_portal_session(
        tenant.get("stripe_customer_id"), f"{base}/dashboard"
    )
    if err:
        raise HTTPException(status_code=503, detail=err)
    return {"url": url}
