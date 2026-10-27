"""SpanTrail Python SDK - lightweight agent tracing.

Usage:
    import spantrail
    spantrail.init(api_key="spantrail_sk_...", endpoint="https://your-host:8443")

    @spantrail.trace("research.run")
    def run(q):
        ...

    with spantrail.span("llm.completion", kind="llm", model="gpt-4o") as s:
        s.input = {"prompt": q}
        ...
        s.output = {"text": "..."}
        s.tokens_input = 120
        s.tokens_output = 340
"""
import os
import time
import uuid
import json
import threading
import atexit
import urllib.request
import urllib.error
from contextlib import contextmanager

__version__ = "0.1.0"

_config = {
    "api_key": None,
    "endpoint": None,
    "verify_tls": True,
    "batch_size": 20,
    "flush_interval": 3.0,
    "service": "unknown",
    "enabled": True,
}

_lock = threading.Lock()
_queue = []
_retry_counts = {}   # id(batch) -> attempts, bounded so a bad payload cannot loop forever
_max_retries = 3
_flush_thread = None

# Per-thread trace context so spans created inside a traced function attach to
# the same trace instead of starting a new one.
_ctx = threading.local()


def _current_trace_id():
    stack = getattr(_ctx, "trace_stack", None)
    return stack[-1] if stack else None


def _current_span_id():
    stack = getattr(_ctx, "span_stack", None)
    return stack[-1] if stack else None


def _push_trace(tid):
    stack = getattr(_ctx, "trace_stack", None)
    if stack is None:
        stack = []
        _ctx.trace_stack = stack
    stack.append(tid)


def _pop_trace():
    stack = getattr(_ctx, "trace_stack", None)
    if stack:
        stack.pop()


def _push_span(sid):
    stack = getattr(_ctx, "span_stack", None)
    if stack is None:
        stack = []
        _ctx.span_stack = stack
    stack.append(sid)


def _pop_span():
    stack = getattr(_ctx, "span_stack", None)
    if stack:
        stack.pop()


def init(api_key=None, endpoint=None, verify_tls=True, service=None, enabled=None):
    """Configure the SDK. Safe to call once at process start."""
    api_key = api_key or os.environ.get("SPANTRAIL_API_KEY")
    endpoint = (endpoint or os.environ.get("SPANTRAIL_ENDPOINT") or "").rstrip("/")
    if service:
        _config["service"] = service
    if enabled is not None:
        _config["enabled"] = bool(enabled)
    if api_key:
        _config["api_key"] = api_key
    if endpoint:
        _config["endpoint"] = endpoint
    _config["verify_tls"] = verify_tls
    _start_flusher()
    return _config


def _active():
    return bool(_config.get("enabled") and _config.get("api_key") and _config.get("endpoint"))


def _now_iso():
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _enqueue(payload):
    if not _active():
        return
    with _lock:
        _queue.append(payload)
        n = len(_queue)
    if n >= _config["batch_size"]:
        flush()


def _post(batch):
    url = _config["endpoint"].rstrip("/") + "/api/v1/ingest"
    data = json.dumps(batch).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": _config["api_key"],
            "User-Agent": f"spantrail-python/{__version__}",
        },
        method="POST",
    )
    ctx = None
    if not _config["verify_tls"]:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return None, str(e).encode()


def _merge(payloads):
    """Merge queued payloads into the single object the ingest API expects."""
    merged = {"traces": [], "spans": [], "logs": []}
    for p in payloads:
        for key in merged:
            merged[key].extend(p.get(key, []))
    return merged


def flush():
    with _lock:
        if not _queue:
            return None
        batch = list(_queue)
        _queue.clear()
    status, body = _post(_merge(batch))
    if status is None or status >= 400:
        # Requeue for retry, but only a bounded number of times so a payload the
        # server always rejects cannot spin forever.
        #
        # The retry count must be attached to the PAYLOAD, not to the list
        # object. Keying on id(list) does not work: CPython reuses the memory
        # address of a freed list, so the counter silently resets and the
        # bound never trips. Use a stable content-derived key instead.
        key = _retry_key(batch)
        attempts = _retry_counts.get(key, 0) + 1
        if attempts <= _max_retries:
            _retry_counts[key] = attempts
            with _lock:
                _queue[:0] = batch
        else:
            _retry_counts.pop(key, None)
    else:
        _retry_counts.pop(_retry_key(batch), None)
    return status


def _retry_key(batch):
    """A stable key for a batch of queued payloads, for retry accounting."""
    import hashlib

    h = hashlib.sha256()
    for payload in batch:
        h.update(repr(sorted(payload.keys())).encode("utf-8"))
        for key in sorted(payload.keys()):
            for item in payload.get(key, []):
                if isinstance(item, dict):
                    h.update(str(item.get("id", "")).encode("utf-8"))
    return h.hexdigest()


def _start_flusher():
    global _flush_thread
    with _lock:
        if _flush_thread and _flush_thread.is_alive():
            return
        _flush_thread = threading.Thread(target=_flush_loop, daemon=True)
        _flush_thread.start()


def _flush_loop():
    while True:
        time.sleep(_config["flush_interval"])
        try:
            flush()
        except Exception:
            pass


@atexit.register
def _final_flush():
    try:
        flush()
    except Exception:
        pass


def new_trace_id():
    return str(uuid.uuid4())


class Span:
    def __init__(self, name, trace_id, kind="step", parent_id=None, model=None, **meta):
        self.id = str(uuid.uuid4())
        self.trace_id = trace_id
        self.parent_id = parent_id
        self.name = name
        self.kind = kind
        self.started_at = _now_iso()
        self.ended_at = None
        self.duration_ms = None
        self.input = None
        self.output = None
        self.error = None
        # `model` is a first-class field, not free-form metadata: the dashboard
        # groups and filters spans by it.
        self.model = model
        self.tokens_input = None
        self.tokens_output = None
        self.cost_usd = None
        self.meta = meta or {}
        self._t0 = time.time()

    def end(self, error=None):
        if self.ended_at:
            return
        self.ended_at = _now_iso()
        self.duration_ms = round((time.time() - self._t0) * 1000, 3)
        if error is not None:
            self.error = str(error)[:4000]

    def to_dict(self):
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "kind": self.kind,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "input": self.input,
            "output": self.output,
            "error": self.error,
            "model": self.model,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "cost_usd": self.cost_usd,
            "meta": self.meta,
        }


@contextmanager
def span(name, trace_id=None, parent_id=None, kind="step", model=None, **meta):
    """Context manager yielding a Span.

    Inherits the enclosing trace id when one is active, so nested spans form
    a tree under the trace created by @spantrail.trace.
    """
    tid = trace_id or _current_trace_id() or new_trace_id()
    pid = parent_id or _current_span_id()
    s = Span(name, tid, kind=kind, parent_id=pid, model=model, **meta)
    _push_span(s.id)
    try:
        yield s
    except Exception as e:
        s.end(error=e)
        _enqueue({"spans": [s.to_dict()]})
        raise
    else:
        s.end()
        _enqueue({"spans": [s.to_dict()]})
    finally:
        _pop_span()


def log(message, level="info", trace_id=None, span_id=None, **meta):
    """Emit a structured log line tied to the active trace."""
    _enqueue(
        {
            "logs": [
                {
                    "trace_id": trace_id or _current_trace_id(),
                    "span_id": span_id,
                    "level": level,
                    "message": str(message),
                    "meta": meta,
                }
            ]
        }
    )


def trace_span(name, trace_id, kind="step", parent_id=None, model=None, **meta):
    """Start a span without a context manager. Call .end() when finished."""
    return Span(name, trace_id, kind=kind, parent_id=parent_id, model=model, **meta)


def trace(name, **meta):
    """Decorator: wraps a function into a trace with one span.

    The wrapped function's return value is passed through untouched. If the
    function raises, the span is recorded with the error and the exception
    is re-raised.
    """
    import functools

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not _active():
                return fn(*args, **kwargs)
            tid = new_trace_id()
            s = Span(name, tid, kind="step", **meta)
            _push_trace(tid)
            # The decorator's own span is the root: child spans created inside
            # the function must point at it via parent_id.
            _push_span(s.id)
            try:
                result = fn(*args, **kwargs)
            except Exception as e:
                s.end(error=e)
                _enqueue(
                    {
                        "traces": [
                            {
                                "id": tid,
                                "name": name,
                                "started_at": s.started_at,
                                "ended_at": s.ended_at,
                                "meta": meta,
                            }
                        ],
                        "spans": [s.to_dict()],
                    }
                )
                raise
            finally:
                _pop_span()
                _pop_trace()
            s.end()
            _enqueue(
                {
                    "traces": [
                        {
                            "id": tid,
                            "name": name,
                            "started_at": s.started_at,
                            "ended_at": s.ended_at,
                            "meta": meta,
                        }
                    ],
                    "spans": [s.to_dict()],
                }
            )
            return result

        return wrapper

    return deco
