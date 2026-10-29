# SpanTrail - autonomous growth plan

## The strategic shift

**We are not promoting "another agent observability tool".** That market is
crowded: Langfuse has 36,624 GitHub stars and 23.5M downloads/month. Our
Python SDK is not a differentiator either - Anthropic now ships native
OpenTelemetry traces from Claude Code, so everyone can already emit spans.

**We are repositioning as the agent spend ledger.** One POST per agent run
gets you three things nobody else gives you together:

1. **One dollar figure per run** - the actual LLM spend, metered on LLM
   spans only. Tool spans ride free.
2. **One shareable link** - the full trace, readable, no login. Paste it in
   Slack and the postmortem is done.
3. **One place to see every agent** - Claude Code, Codex, Cursor, LangGraph,
   your own code.

### Why the billing model is the moat

Langfuse meters "units" = traces + observations + scores, $8/100k over the
Core allowance. A tool-heavy deploy agent produces 2 model calls and 30 tool
calls - so flat per-span billing taxes **exactly the behaviour you want**
(agents that check state, read logs, and verify before acting) at 15x what
its model calls justify.

Datadog and Langfuse's own cost engine already meter LLM spans only. We
adopt that as our public pricing. This is defensible because a competitor
would have to **cannibalise their own metering** to copy it. Features get
copied; a pricing model does not.

### Who this is for

Not LangSmith's enterprise buyer. Not Langfuse's self-hoster.

**The solo dev and small team running Claude Code / Codex / Cursor who needs
to answer "what did my agent cost me, and why did it do that?" - and who
will not deploy six containers to find out.**

That is also the person who reads dev.to, watches Show HN, installs Claude
Code plugins, and lives in Discord. Our distribution channels and our buyer
are the same person.

---

## The five channels, in order

### 1. PyPI - the SDK is the billboard

Every `pip install spantrail` puts our name in their terminal and in their
requirements.txt forever. Langfuse gets 23.5M downloads/month on this
channel alone. It is the one channel where the user has already asked for us.

**Build:** a first-class integration, not just a client. The SDK must read
the local session files Claude Code, Codex and Cursor already write, so
`spantrail.init()` is all it takes.

**Why it's autonomous:** we own the package. Publishing is `twine upload`.

### 2. MCP server - become infrastructure agents call

The official MCP Registry is backed by Anthropic, GitHub, PulseMCP and
Microsoft. It has a documented "Publish my MCP server" flow via a GitHub PR.

We publish a **SpanTrail MCP server** exposing `spantrail_query_cost`,
`spantrail_get_trace`, `spantrail_list_runs`. Then an agent can ask itself
"what did I spend last week?" - and the answer routes through our API. Every
agent that uses it is a durable, recurring user.

**Why it's autonomous:** a GitHub PR to a public repo. No approval needed.

### 3. Claude Code + OpenAI plugin directories

Claude Code plugins install from a `.claude-plugin/marketplace.json`. OpenAI
runs a universal plugin directory shared by ChatGPT and Codex. Both surfaces
are exactly where our buyer already is - they are *in* Claude Code.

Ship a **SpanTrail plugin** that instruments the agent's own runs and posts
the trace + cost back. Zero-config: the buyer runs one command.

**Why it's autonomous:** our own marketplace is a GitHub repo; Anthropic's
directory needs one submission + human review.

### 4. Programmatic SEO - the compounding channel

The devtool SEO pattern that earns: **integration pages**. "Trace Claude
Code with SpanTrail", "LangGraph + SpanTrail", "MCP server tracing",
"OpenAI Agents SDK". Each is a real, useful page that ranks for a query
with clear intent.

We generate these from a template + a structured dataset, each one actually
containing working code. This is the only channel that compounds without
daily effort.

**Why it's autonomous:** a generator + a cron job.

### 5. dev.to - where the buyer reads

The Forem API (`POST /api/articles`, ~10 requests / 30 s) is explicitly
built for programmatic publishing. We publish genuinely useful technical
posts - not marketing. The angle that works: *"I traced 10,000 agent runs
and found the tool calls that cost more than the model calls"*.

**Why it's autonomous:** an API.

---

## What I will NOT do

| Channel | Why not |
|---|---|
| **Hacker News** | HN explicitly forbids automated posting and generated text. Humans only, never automated. |
| **Reddit** | The Data API needs approved-developer status and a Responsible Builder review. Unapproved automation risks a permanent ban. |
| **Discord** | Per-server rules vary; spam gets us removed. Human-only, low priority. |
| **Paid ads** | No budget, no proof of payback. Never autonomous. |
| **Product Hunt** | One launch, not a channel. Worth doing once, at the right moment, with a human present. |

---

## The weekly autonomous loop

| Day | Action | Cost | Expected effect |
|---|---|---|---|
| Mon | Publish a dev.to post (technical, non-promotional) | $0 | Referral traffic |
| Tue | Generate + publish 5 programmatic SEO pages | $0 | Compounds |
| Wed | PyPI release if the SDK changed | $0 | Downloads |
| Thu | dev.to post | $0 | Referral traffic |
| Fri | SEO batch + metrics review | $0 | Compounds |
| Daily | Health, uptime, metrics, error triage | $0 | Keeps the product alive |
| Weekly | Reddit/HN drafts **for you to post by hand** | your 2 min | Highest-quality traffic |

---

## The metrics that decide whether this works

| Metric | Where from | Now | 90-day target |
|---|---|---|---|
| PyPI downloads/month | pypistats API | 0 | 5,000 |
| GitHub stars | GitHub API | 0 | 500 |
| Registered tenants | our DB | 1 (you) | 50 |
| Paid subscribers | Stripe | 0 | 5 |
| Traces ingested/month | our DB | 0 | 1,000,000 |
| Site sessions | analytics | 0 | 10,000 |
| Revenue MRR | Stripe | $0 | $145 |

**The one metric that matters: traces ingested per week.** Everything else
is vanity. If developers are not wiring SpanTrail into their agents, no
amount of promotion will produce revenue.

---

## The gates - your approval required at each

| # | Gate | What I need from you | What it unlocks |
|---|---|---|---|
| **1** | **Live mode** | the Stripe live key + PyPI token | Real money can be taken. Everything else is a rehearsal. |
| **2** | **Positioning sign-off** | one sentence: "the agent spend ledger" | I rewrite the landing page, README and the pricing page around it. Cheap, reversible, and everything downstream depends on it. |
| **3** | **Plugin directory submissions** | submit Anthropic's directory + OpenAI's | Two human-reviewed submissions that reach the installed base. |
| **4** | **A real card** | buy your own Pro plan with a real card | Proves the live path end-to-end and gives us a real customer reference. |
| **5** | **HN / Reddit** | you post by hand, twice in the first month | Highest-quality traffic. I write and queue the drafts. |

**You approve the plan once and I run it.** You will only be interrupted at
the gates above. Everything else - writing, publishing, measuring, fixing -
is mine.

---

## Why you can be nearly absent

- **No content decisions needed from you.** I write the posts, the SEO pages,
  the docs. You do not approve content.
- **No pricing decisions needed from you.** The model is set by the
  competitive research, not taste.
- **No ops decisions needed from you.** Deploys, health checks, retention,
  billing - all autonomous, all verified.
- **You approve money-moving and reputation-moving actions once**, at the
  gates.

The honest risk: **the first 90 days are probably mostly code, not
marketing.** The product needs the SDK to read local session files before
any promotion pays off. Promotion amplifies something that already works; it
does not create it.

---

## Phase plan

### Phase 0 - Live mode (blocked on gate 1)
Publish to PyPI. Switch Stripe to live. Both need your two secrets. I have
the script; it is `bash publish_all.sh`.

### Phase 1 - Reposition (week 1-2, no input needed)
Rewrite the landing page, README and pricing around the spend-ledger
position. Add the "one POST per run" quickstart. Ship a working
`examples/` directory. Add the shareable trace link (no-login view).

### Phase 2 - The SDK becomes a product (week 2-4)
Read Claude Code / Codex / Cursor session files natively. Ship the MCP
server. Publish to the official MCP Registry. Ship the Claude Code plugin.

### Phase 3 - The compounding channel (week 3-6)
The programmatic SEO generator: one template, a structured dataset of
integrations, real working code in every page. Plus the dev.to cadence.

### Phase 4 - Revenue (week 6+)
The first real customer. The HN post you write by hand. Iterate on what
the metrics say.

---

## What I need from you right now

**Gate 1**, so the rest can start: run

```bash
cd "C:/claude projects/spantrail" && bash publish_all.sh
```

and paste the PyPI token and the Stripe live key into the two hidden
prompts.

**Gate 2** is a one-word confirmation. I propose the positioning line:

> **SpanTrail tells you what your agent cost you, and why it did that.**
> One number per run. One link per failure. No six-container deployment.

Say "go" and I will start Phase 1 the same hour.
