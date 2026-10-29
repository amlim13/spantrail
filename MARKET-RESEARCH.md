# SpanTrail - market research and promotion strategy
Researched 2026-10-29. Sources verified with live fetches.

## The market

| Competitor | Traction | Stack | Cloud price |
|---|---|---|---|
| **Langfuse** | 36,624 GitHub stars | 6 containers: web + worker + Postgres + ClickHouse + Redis + MinIO. ~2 CPU/4 GiB each | Hobby free 50k units/mo; Core $29 (100k units, $8/100k over); Pro $199; Enterprise $2,499 |
| LangSmith | proprietary | - | Free 5k traces; usage-metered |
| Braintrust / Helicone / Arize / Datadog | proprietary | - | span/unit-metered |
| **Otterscope** | OSS | one static binary + one SQLite file | - |
| OpenTrace / agentpond / tma1 / traces(archived) | OSS | single binary / DuckDB / GreptimeDB | - |
| ClawMetry / agent-trail / tokmeter / tokentaby / Kibble | OSS + SaaS | read local session JSONL | Kibble = team SaaS |

Baseline downloads (pypistats, 2026-10-29): langfuse 23.5M/mo, opentelemetry-sdk 260M/mo,
posthog 39.8M/mo.

## Facts that shape the strategy

1. **"Agent observability" is a commodity.** Langfuse alone has 36k stars.
   A generic "traces for agents" product is undifferentiated.

2. **The self-host gap is real but small.** Langfuse self-hosting needs 6
   containers and ~12 GiB. People want less. But that niche is already
   crowded: Otterscope (one binary, one SQLite), OpenTrace (Rust reverse
   proxy), agentpond, tma1. **We cannot win "one box, one file".**

3. **The SDK is now a commodity input.** Anthropic ships native OpenTelemetry
   traces from Claude Code / the Agent SDK (`CLAUDE_CODE_ENABLE_TELEMETRY=1`,
   `OTEL_TRACES_EXPORTER`). The OpenTelemetry GenAI semantic conventions are
   the industry standard. **Our Python SDK is no longer a differentiator.**

4. **The billing model is contested.** Langfuse meters traces + observations
   + scores ("units"), $8/100k. Datadog and Langfuse's cost engine meter
   **LLM/generation spans only** - tool spans ride free. The complaint:
   "a deploy agent makes 2 model calls and 30 tool calls; flat per-span
   billing taxes exactly the behaviour you want." Langfuse's own pricing
   shows the arbitrage: Hobby is 50k units, Core is 100k units, Pro is
   100k + unlimited history.

5. **HN forbids automation.** "Please don't put generated text in HN posts.
   Write your text yourself... please don't automate posting." Same for
   comments. **We cannot run an auto-poster on HN or in HN threads.**

6. **Reddit's API is gated.** The Data API requires an approved developer
   account and a "Responsible Builder Policy" review; commercial use needs
   explicit approval. Automated cross-posting without approval risks a ban.

7. **Autonomous posting is allowed where an API exists.** dev.to's Forem API
   (`POST /api/articles`, ~10 requests / 30 s) is built for it. Product Hunt
   has an official GraphQL API 2.0. The MCP Registry is an official
   GitHub-backed repo with a documented "Publish my MCP server" flow.
   Claude Code has a plugin marketplace + Anthropic's directory. OpenAI has
   a universal plugin directory shared by ChatGPT and Codex.

8. **Distribution beats promotion for devtools.** The 2026 consensus:
   "DevTools buyers prioritize documentation, GitHub activity, and community
   signals over traditional B2B marketing content, so generic playbooks
   underperform." Programmatic SEO that earns for devtools = integration
   pages ("connect <tool A> to <tool B>"), error references, comparison pages.

## The gap we can actually own

Everyone has one of: a full platform (Langfuse), a local single-file viewer
(Otterscope), or a cost ledger (Kibble, tokmeter). Nobody has:

**The bill.**

- Langfuse: you must deploy 6 containers, and you pay per unit across
  traces + observations + scores - so a tool-heavy agent costs 15x more than
  its model calls justify.
- Otterscope et al: local only, no team view, no shareable link, no billing.
- Kibble/tokmeter: they read local JSONL and estimate cost - they cannot
  tell you what the agent DID, only what it cost.

**SpanTrail should be the agent spend + behaviour ledger: one POST per agent
run, one dollar figure, one shareable trace link.** Meter LLM spans only,
trace everything else free - the class-aware pricing Datadog and Langfuse's
cost engine already use internally. Price at a flat monthly ceiling.

That is a defensible position because it is a *pricing* position, not a
*feature* position. Features get copied; a billing model that a competitor
would have to cannibalise their own metering to copy, does not.

## The channels, ranked by (reach x autonomy x legality)

| # | Channel | Reach | Autonomy | Notes |
|---|---|---|---|---|
| 1 | PyPI | 23M/mo scale for langfuse | Full | The SDK is the distribution vehicle. Every `pip install spantrail` is a billboard. |
| 2 | MCP Registry (official) | Growing fast | Full | Anthropic + GitHub backed. We become infrastructure an agent can call. |
| 3 | Claude Code plugin dir / OpenAI plugin dir | Large installed base | One approval | CLI users are exactly the buyer. |
| 4 | GitHub + OTel registry + awesome lists | Compounds | Full | Long tail, evergreen. |
| 5 | dev.to API | Real traffic | Full | Allowed. ~1 article / 30 s. |
| 6 | Programmatic SEO | Compounds | Full | Integration pages = the classic devtool SEO pattern. |
| 7 | Product Hunt API | One shot/day | Full | One launch, not a channel. |
| 8 | Reddit | Large | **Gated** | Needs API approval + human-written posts. |
| 9 | HN | Highest quality | **Banned** | No automation. Human only. |
| 10 | Discord | Medium | Partial | Agents can post, but rules differ per server. |

## Baselines to beat

- GitHub stars: **0**
- PyPI: **does not exist** (404)
- Domain: live, 200
- Stripe: test mode, one Pro sub (self)
- Customers: **0**
