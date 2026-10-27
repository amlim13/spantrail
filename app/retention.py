"""Nightly retention purge: drop data older than 30 days (configurable)."""
import os
import datetime as dt

import db

RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "30"))


def main():
    db.apply_schema()
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RETENTION_DAYS)
    with db.cursor() as cur:
        cur.execute("SELECT id FROM tenants WHERE status <> 'cancelled'")
        tenant_ids = [r["id"] for r in cur.fetchall()]

        cur.execute("DELETE FROM spans WHERE created_at < %s", (cutoff,))
        spans = cur.rowcount
        cur.execute("DELETE FROM logs WHERE created_at < %s", (cutoff,))
        logs = cur.rowcount
        cur.execute("DELETE FROM traces WHERE started_at < %s", (cutoff,))
        traces = cur.rowcount
        cur.execute("DELETE FROM events_daily WHERE day < %s", (cutoff.date(),))
        daily = cur.rowcount

    print(
        f"retention {RETENTION_DAYS}d cutoff={cutoff.isoformat()} "
        f"traces={traces} spans={spans} logs={logs} daily_rows={daily} "
        f"active_tenants={len(tenant_ids)}"
    )


if __name__ == "__main__":
    main()
