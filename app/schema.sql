-- SpanTrail (agent observability) schema
-- Idempotent. Applied on API startup.

CREATE TABLE IF NOT EXISTS tenants (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL,
    email        TEXT,
    api_key_hash TEXT NOT NULL UNIQUE,
    status       TEXT NOT NULL DEFAULT 'active',   -- pending | active | cancelled
    plan         TEXT NOT NULL DEFAULT 'free',
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    activated_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS tenants_status_idx ON tenants (status);

CREATE TABLE IF NOT EXISTS traces (
    id         UUID PRIMARY KEY,
    tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    session_id TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at   TIMESTAMPTZ,
    meta       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS traces_tenant_created_idx ON traces (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS traces_tenant_started_idx ON traces (tenant_id, started_at DESC);

CREATE TABLE IF NOT EXISTS spans (
    id            UUID PRIMARY KEY,
    tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    trace_id      UUID NOT NULL,
    parent_id     UUID,
    name          TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'step',   -- step | llm | tool | retrieval | code | http
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at      TIMESTAMPTZ,
    duration_ms   DOUBLE PRECISION,
    input         JSONB,
    output        JSONB,
    error         TEXT,
    model         TEXT,
    tokens_input  INTEGER,
    tokens_output INTEGER,
    cost_usd      DOUBLE PRECISION,
    meta          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS spans_tenant_created_idx ON spans (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS spans_trace_idx ON spans (trace_id);
CREATE INDEX IF NOT EXISTS spans_tenant_kind_idx ON spans (tenant_id, kind);

CREATE TABLE IF NOT EXISTS logs (
    id         BIGSERIAL PRIMARY KEY,
    tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    trace_id   UUID,
    span_id    UUID,
    level      TEXT NOT NULL DEFAULT 'info',
    message    TEXT NOT NULL,
    meta       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS logs_tenant_created_idx ON logs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS logs_trace_idx ON logs (trace_id);

-- Rolling 30 day retention (tenant data older than this is purged nightly).
CREATE TABLE IF NOT EXISTS events_daily (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    day       DATE NOT NULL,
    traces    INTEGER NOT NULL DEFAULT 0,
    spans     INTEGER NOT NULL DEFAULT 0,
    errors    INTEGER NOT NULL DEFAULT 0,
    tokens_in BIGINT NOT NULL DEFAULT 0,
    tokens_out BIGINT NOT NULL DEFAULT 0,
    cost_usd  DOUBLE PRECISION NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, day)
);
