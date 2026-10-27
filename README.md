# SpanTrail

**See what your agent actually did.**

SpanTrail records every tool call, prompt, token and error your AI agent
produces, then gives you a timeline you can actually read.

```bash
pip install spantrail
```

```python
import spantrail

spantrail.init(
    api_key="spantrail_sk_...",
    endpoint="https://spantrail.com",
    service="my-agent",
)

@spantrail.trace("research.run")
def research(query):
    with spantrail.span("llm.completion", kind="llm", model="gpt-4o") as s:
        s.input = {"prompt": query}
        s.output = {"text": "..."}
        s.tokens_input = 120
        s.tokens_output = 340
        s.cost_usd = 0.004
        return "..."

research("what changed in agent frameworks this month?")
```

That's the whole integration. Your existing function keeps working unchanged -
the SDK never raises into your application if the SpanTrail endpoint is
unreachable. Failed batches are retried a bounded number of times and then
dropped.

---

## Why

Agent failures are invisible. The run "succeeded" and the output was wrong -
no stack trace, no record of which tool call drifted. Token spend is
discovered after the fact and attributed by guesswork. Reproducing a failure
means re-running the agent against a live world and hoping it fails the same
way twice.

SpanTrail answers three questions:

- **What did it do?** Every span in order: name, duration, inputs, outputs,
  errors, token counts, cost. Click any trace for the full tree.
- **What did it cost?** Cost is attached to the span that incurred it, not to
  a monthly total you have to reverse-engineer.
- **Where did it break?** Exceptions are captured with their message and the
  span stack, so a failed run is a link you can send to a colleague.

## Install

```bash
pip install spantrail
```

Python 3.8+, zero dependencies. The SDK is a single module.

From a local build (no PyPI yet):

```bash
pip install https://spantrail.com/dist/spantrail-0.1.0-py3-none-any.whl
```

## Configuration

| Env var | Meaning |
|---|---|
| `SPANTRAIL_API_KEY` | Your API key (`spantrail_sk_...`) |
| `SPANTRAIL_ENDPOINT` | Base URL, e.g. `https://spantrail.com` |
| `SPANTRAIL_VERIFY_TLS` | Set to `0` only for self-signed certs |

`spantrail.init()` takes the same values as keyword arguments and wins over
the environment.

## API

| Call | What it does |
|---|---|
| `spantrail.init(...)` | Configure the SDK. Call once at process start. |
| `spantrail.trace(name)` | Decorator. One trace + one root span per call. |
| `spantrail.span(name, kind=...)` | Context manager for nested work. Inherits the enclosing trace. |
| `spantrail.log(message, level=...)` | Structured log line, attached to the active trace. |
| `spantrail.flush()` | Force a flush. Also runs automatically at exit. |

### Span kinds

`kind` is a free-form string, but these are what the dashboard groups by:

| kind | For |
|---|---|
| `step` | A generic unit of work (the default) |
| `llm` | A model call - set `model`, `tokens_input`, `tokens_output`, `cost_usd` |
| `tool` | A tool invocation |
| `retrieval` | A search, RAG lookup, or DB read |
| `code` | Code execution |
| `http` | An outbound HTTP call |

### Cost

Set `cost_usd` on the span that incurred it. SpanTrail does not guess your
rates and does not talk to any LLM provider - your pricing, your numbers.
If you want per-span cost computed from a rate card, compute it in your code
and set the field.

## How it works

- Events are batched in-process and flushed every few seconds over HTTPS.
- The payload is one object: `{"traces": [...], "spans": [...], "logs": [...]}`.
- API keys are stored as SHA-256 hashes. A key is shown once, at creation.
- 30-day retention by default.

## Dashboard

`https://spantrail.com/dashboard` - paste your API key, no account needed.

Shows: spans in 24h, errors in 24h, p50/p95/p99 latency, cost 24h and 30d,
a trace list, a span feed, and a usage panel with your plan's event budget.

## Self-hosting

SpanTrail runs on a single small box - 2 vCPU and 4 GB is plenty for a
meaningful number of users.

- **Postgres 16** - traces, spans, logs, tenants
- **Caddy** - TLS and the static site
- **FastAPI** - the ingest and read API
- Three systemd units in one cgroup slice with hard `MemoryMax`/`CPUQuota`

The whole product is a few thousand lines of Python. See `RUNBOOK.md` in the
repository for the deployment procedure.

## Privacy

- Prompt bodies stay in your process. The SDK sends metadata (name, kind,
  duration, token counts, cost, and whatever you explicitly put in
  `input`/`output`) - it does not read your prompts unless you assign them.
- No outbound calls to LLM providers from the SpanTrail runtime. Your provider
  keys never touch our infrastructure.
- The API key is the only credential, and it is stored hashed.

## License

MIT
