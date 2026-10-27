import os
import contextlib
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor

_pool = None


def _load_env_file(path="/opt/spantrail/app/.env"):
    """Load the app .env into os.environ if the key is not already set.

    systemd's EnvironmentFile handles the services; this covers direct
    invocations (admin CLI, cron-style scripts, the retention job).
    """
    if "DATABASE_URL" in os.environ:
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except OSError:
        pass


_load_env_file()


def get_pool():
    global _pool
    if _pool is None:
        dsn = os.environ["DATABASE_URL"]
        _pool = ThreadedConnectionPool(1, 10, dsn)
    return _pool


@contextlib.contextmanager
def conn():
    pool = get_pool()
    c = pool.getconn()
    try:
        yield c
        c.commit()
    except Exception:
        try:
            c.rollback()
        except Exception:
            pass
        raise
    finally:
        pool.putconn(c)


@contextlib.contextmanager
def cursor():
    with conn() as c:
        with c.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur


def apply_schema():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "schema.sql"), "r", encoding="utf-8") as f:
        sql = f.read()
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(sql)


def health():
    with cursor() as cur:
        cur.execute("SELECT 1 AS ok")
        return cur.fetchone()["ok"] == 1
