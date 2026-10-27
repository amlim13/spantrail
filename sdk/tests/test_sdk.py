"""Tests for the SpanTrail SDK.

These run without a server: the SDK's HTTP layer is monkeypatched so we can
assert on exactly what would be sent.

    python -m pytest
"""
import json
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk"))

import spantrail  # noqa: E402


class FakeTransport:
    """Captures the requests the SDK would send."""

    def __init__(self, status=200):
        self.status = status
        self.batches = []

    def __call__(self, batch):
        self.batches.append(batch)
        return self.status, b"{}"


@pytest.fixture
def transport(monkeypatch):
    t = FakeTransport()
    monkeypatch.setattr(spantrail, "_post", t)
    spantrail.init(
        api_key="spantrail_sk_test",
        endpoint="https://spantrail.com",
        service="test",
    )
    spantrail._queue.clear()
    spantrail._retry_counts.clear()
    return t


def test_init_sets_config():
    spantrail.init(api_key="k", endpoint="https://x.test", service="svc")
    assert spantrail._config["api_key"] == "k"
    assert spantrail._config["endpoint"] == "https://x.test"
    assert spantrail._config["service"] == "svc"


def test_trace_creates_one_trace_and_one_span(transport):
    @spantrail.trace("unit.test")
    def work():
        return 42

    assert work() == 42
    spantrail.flush()

    assert len(transport.batches) == 1
    batch = transport.batches[0]
    assert len(batch["traces"]) == 1
    assert len(batch["spans"]) == 1
    assert batch["traces"][0]["name"] == "unit.test"
    assert batch["spans"][0]["trace_id"] == batch["traces"][0]["id"]


def test_trace_propagates_exception_and_records_error(transport):
    @spantrail.trace("unit.boom")
    def boom():
        raise ValueError("kaboom")

    with pytest.raises(ValueError):
        boom()
    spantrail.flush()

    batch = transport.batches[0]
    assert len(batch["spans"]) == 1
    assert "kaboom" in batch["spans"][0]["error"]


def test_nested_spans_share_the_trace_and_form_a_tree(transport):
    @spantrail.trace("unit.nested")
    def outer():
        with spantrail.span("child.a", kind="llm") as a:
            a.tokens_input = 5
            a.tokens_output = 7
            a.cost_usd = 0.01
            with spantrail.span("child.b", kind="tool"):
                pass

    outer()
    spantrail.flush()

    batch = transport.batches[0]
    spans = batch["spans"]
    assert len(spans) == 3

    trace_ids = {s["trace_id"] for s in spans}
    assert len(trace_ids) == 1, "all spans must share one trace_id"

    roots = [s for s in spans if s["parent_id"] is None]
    assert len(roots) == 1, "exactly one root span"

    by_id = {s["id"]: s for s in spans}
    for s in spans:
        if s["parent_id"] is not None:
            assert s["parent_id"] in by_id, "parent must resolve within the trace"
            assert by_id[s["parent_id"]]["trace_id"] == s["trace_id"]


def test_span_records_cost_and_tokens(transport):
    @spantrail.trace("unit.cost")
    def work():
        with spantrail.span("llm", kind="llm", model="gpt-4o") as s:
            s.tokens_input = 120
            s.tokens_output = 340
            s.cost_usd = 0.0041

    work()
    spantrail.flush()

    llm = [s for s in transport.batches[0]["spans"] if s["kind"] == "llm"][0]
    assert llm["tokens_input"] == 120
    assert llm["tokens_output"] == 340
    assert llm["cost_usd"] == 0.0041
    assert llm["model"] == "gpt-4o"


def test_log_attaches_to_the_active_trace(transport):
    @spantrail.trace("unit.log")
    def work():
        spantrail.log("something happened", level="warning")

    work()
    spantrail.flush()

    batch = transport.batches[0]
    assert len(batch["logs"]) == 1
    log = batch["logs"][0]
    assert log["message"] == "something happened"
    assert log["level"] == "warning"
    assert log["trace_id"] == batch["traces"][0]["id"]


def test_flush_merges_multiple_payloads_into_one_object(transport):
    @spantrail.trace("unit.merge")
    def work():
        pass

    work()
    work()
    spantrail.flush()

    assert len(transport.batches) == 1
    batch = transport.batches[0]
    # The API expects ONE object, not a list. This is the exact bug that
    # caused 422s in production, so it is asserted explicitly.
    assert isinstance(batch, dict)
    assert set(batch.keys()) == {"traces", "spans", "logs"}
    assert len(batch["traces"]) == 2


def test_failed_flush_is_retried_a_bounded_number_of_times(monkeypatch):
    t = FakeTransport(status=500)
    monkeypatch.setattr(spantrail, "_post", t)
    spantrail.init(api_key="k", endpoint="https://x.test", service="t")
    spantrail._queue.clear()
    spantrail._retry_counts.clear()

    @spantrail.trace("unit.retry")
    def work():
        pass

    work()
    for _ in range(10):
        spantrail.flush()

    # Bounded: it must not retry forever.
    assert len(t.batches) <= 5, "retries must be bounded"
    assert len(spantrail._queue) <= 1


def test_disabled_sdk_is_a_noop(monkeypatch):
    monkeypatch.setattr(spantrail, "_post", FakeTransport())
    spantrail.init(api_key="", endpoint="", enabled=False)
    spantrail._queue.clear()

    @spantrail.trace("unit.disabled")
    def work():
        return "ok"

    assert work() == "ok"
    assert spantrail._queue == [], "a disabled SDK must not queue anything"
