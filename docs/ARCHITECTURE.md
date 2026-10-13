# Rookwise: Architecture

Source of truth for humans and coding agents (Claude Code, GLM). Version of October 13, 2026.
Hackathon: Nebius x NVIDIA Global AI Hackathon 2026, track Best Apps and Agents. Submission deadline: October 30, 2026, 10:00 AM PDT.

## Rules for any agent working in this repo

- Write all code, comments, docs and UI text in English.
- Never expose keys. Keys live in `.env` (see `.env.example`) or in server-side environment variables. Never commit a key, never print it, never send it to the browser.
- Prices are never hard-coded. Read them from `config/prices.json`.
- Do not assume API details. Check `docs/HARNESS_RESEARCH.md` first and mark anything unverified as such.
- Every module in `core/` ships with tests in `tests/`.
- Ownership: `core/` is built with Claude Code. `web/` is built with GLM. They only talk through the API described in `docs/api.md` (written by Claude Code before the web UI starts).
- Report results exactly as measured. Do not invent numbers.

## Summary

A hierarchical team of AI agents with a controlled token budget. The user sets a goal and a spending cap. The system splits the goal, hires operators from a catalog with price, speed and reputation, runs them in parallel, audits the result, and returns a verifiable package showing real cost next to predicted cost.

Thesis to test with our own measurements: a hierarchy that uses a different model per level costs less than running the largest model for everything, with comparable quality according to an independent auditor. If the benchmark does not confirm it, we report what we measured.

Runs on NVIDIA Nemotron models on Nebius Token Factory. Demo cases are simulated and labeled as simulated. Kosmo (an in-house small language model under development) is a roadmap item and is not part of this submission.

## Hackathon requirements

Source: the team's summary of the hackathon rules. **Verify against the Devpost page before submitting.**

| Requirement | How Rookwise meets it | Status |
|---|---|---|
| Run on Nebius Token Factory or Nebius AI Cloud | All model calls go to Token Factory | Planned |
| Use at least one NVIDIA open source model | NVIDIA Nemotron at every level | Planned |
| Working demo with a URL | Vercel deployment of `web/` (recorded and live modes) | Planned (Phase 3) |
| Public YouTube video, 3 minutes or less | Demo video | Planned (Phase 5) |
| Public repo with an open source license visible at the top, and a README | MIT `LICENSE` in the repo root; README written in Phase 5 | License done, README planned |
| Feedback on Nebius and NVIDIA | `FEEDBACK.md`, kept from day one | In progress |
| One category | Best Apps and Agents | Chosen |
| Project description | Devpost text | Planned (Phase 5) |
| Optional: Best Use of Tavily bonus | Researcher operators use Tavily search | Planned |

## Levels

| Level | Role | Proposed model |
|---|---|---|
| User (chair) | Sets goal and cap, approves, directs everything | n/a |
| Vice president (only with a board) | Only voice toward the user. Splits the goal among directors | Ultra |
| Director | Analyzes, splits, predicts trajectories and costs, picks the plan. Without a board it is the only agent that talks to the user | Ultra |
| Managers | Optimize a block of the plan, hire operators, consolidate | Super (Lightning to be tested) |
| Operators | One task at a time, parallel across operators | Lightning (Super for hard tasks) |
| Independent auditor | Validates the final deliverable in a separate context | Ultra, different prompt and context |
| Administrator layer | Budget, caps, retries, concurrency | Deterministic code, no model |
| Harness | Runtime that calls models, runs tools, validates output, reports usage | Code, no model |

Communication is vertical. Operators talk to their manager, managers to the director, and only the director (or the VP with a board) talks to the user.

## Flow of a run

1. The user writes the goal and the spending cap.
2. The administrator layer opens the budget ledger.
3. The director produces the plan: tasks, dependencies, 2 or 3 candidate trajectories with predicted cost and time, and picks one.
4. The user approves or adjusts.
5. The administrator layer assigns sub-budgets per manager and task.
6. Managers hire operators from the catalog.
7. Operators execute, save results in the shared store, send their manager a JSON message with a reference.
8. Managers validate and consolidate, report to the director.
9. The director checks against the goal; the auditor validates the deliverable.
10. The director (or VP) hands the package to the user for approval and next directives.
11. The ledger closes and operator reputation updates.

## Administrator layer (deterministic code)

- Reserve budget before each call, charge real cost after.
- Caps per run, per level and per task.
- Record input, cached, output and reasoning tokens, model, cost and time of every call.
- Stop at a cap and return the partial result.
- Limit retries and concurrency. Rate limiting and concurrency are per model and read from `config/rate_limits.json`. The administrator enforces requests per minute and tokens per minute for each model before reserving a call.
- Honor the user's brake: pause, resume, cancel.

### Cost of a call

Prices come from `config/prices.json` in USD per 1M tokens, so each product below is divided by 1,000,000.

```
cost = (input_tokens - cached_tokens) x price_in
     + cached_tokens x price_cached_in
     + output_tokens x price_out
```

- `input_tokens` is `usage.prompt_tokens`. `cached_tokens` is `usage.prompt_tokens_details.cached_tokens` (VERIFIED as a field in the docs); treat a missing value as 0. Whether Token Factory reports non-zero cached tokens for Nemotron is UNVERIFIED.
- `price_cached_in` is the optional `cached_input` price per model in `config/prices.json`. It is `null` for every model because no cached price is published in what we have. When it is `null`, the ledger uses `price_in` for cached tokens and says so: the ledger entry carries `"cached_price_fallback": true`.
- `output_tokens` is `usage.completion_tokens`. Reasoning tokens (`usage.completion_tokens_details.reasoning_tokens`) are treated as output tokens until verified. UNVERIFIED: whether they are billed and whether `completion_tokens` already includes them. If a response reports more reasoning tokens than completion tokens, they are clearly not included and are added to `output_tokens`. The smoke test must compare billed usage against the console billing before any of this is marked VERIFIED.

## Harness (`core/harness/`)

The harness is the only code that talks to the model API. Agents are built on top of it and never call the API directly.

Every model call is gated by the administrator layer. Before each call the harness asks it to RESERVE budget for that call (a worst-case estimate from the prompt size, `max_tokens` and the model's prices). After the call it reports the real usage, and the administrator layer charges the real cost and releases the rest of the reservation. No model call happens without a reservation; if the reservation is refused, the call is not made.

Responsibilities:
- Reserve budget with the administrator layer before every model call, and report real usage after it.
- Send chat completions to Token Factory and return text, tool calls and usage.
- Run the tool loop: model proposes `tool_calls`, harness executes them (for example Tavily search), appends `tool` messages, calls the model again, up to a step cap. Each step is a model call, so each step needs its own reservation.
- Validate output against a schema (task_v1, result_v1) and retry within limits.
- Treat `finish_reason: "length"` as a failure, even when some content came back. Retry within limits with a larger `max_tokens` or with reasoning off, and charge every attempt to the ledger. (Observed in the smoke test: Lightning with reasoning on hit the 600-token limit in 6 of its 11 successful calls, 5 of them with no final answer.)
- Choose the reasoning mode per call by role. Reasoning off is the starting default for operators, to be confirmed by the benchmark.
- Set `max_tokens` to cover reasoning plus the answer: reasoning tokens count inside `completion_tokens` and share the same `max_tokens` limit.
- Respect rate limits: read `x-ratelimit-*` headers, honor `Retry-After` on HTTP 429, back off with a queue.
- Model-agnostic interface: a model is a name, an endpoint, a price entry and a few flags, so non-Nemotron models can be added later.

What is verified and what is not is tracked in `docs/HARNESS_RESEARCH.md`.

## Operator catalog

Each operator is a catalog entry with role, model, price estimate, latency, reputation, tools and schemas.

```json
{
  "operator_id": "researcher-lightning-01",
  "role": "researcher",
  "model": "nemotron-3.5-lightning",
  "price_per_task_est_usd": 0.002,
  "avg_latency_s": 8,
  "reputation": 0.82,
  "tools": ["tavily_search"],
  "input_schema": "task_v1",
  "output_schema": "result_v1"
}
```

Selection: lowest expected cost that meets a minimum reputation and maximum latency. Reputation is a moving average of auditor acceptance. All numbers above are placeholders until measured.

## Messages and shared store

Messages carry ids and references, not content. Content lives in the store (Supabase Postgres in production, SQLite for tests), behind one interface.

```json
// task_v1 (manager to operator)
{
  "task_id": "t-014",
  "run_id": "r-003",
  "role": "copywriter",
  "instruction_ref": "store://r-003/briefs/t-014",
  "inputs": ["store://r-003/results/t-011"],
  "budget": {"max_input_tokens": 12000, "max_output_tokens": 2500, "max_usd": 0.004},
  "deadline_s": 60
}

// result_v1 (operator to manager)
{
  "task_id": "t-014",
  "status": "ok",
  "output_ref": "store://r-003/results/t-014",
  "usage": {"input_tokens": 9800, "output_tokens": 1900, "usd": 0.00105},
  "self_check": {"schema_valid": true, "notes": ""}
}

// ledger_entry
{
  "run_id": "r-003",
  "level": "operator",
  "task_id": "t-014",
  "model": "nemotron-3.5-lightning",
  "input_tokens": 9800,
  "cached_tokens": 0,
  "output_tokens": 1900,
  "reasoning_tokens": 0,
  "cached_price_fallback": true,
  "usd_real": 0.00105,
  "usd_predicted": 0.00120,
  "ts": "2026-10-20T15:02:11Z"
}
```

## Models, prices and cost estimate

Prices and speeds from the Nebius console model cards, read October 12, 2026.

| Model | Input (USD / 1M) | Output (USD / 1M) | Listed speed | Region |
|---|---|---|---|---|
| Nemotron-3-Ultra-550b-a55b | 1.00 | 3.00 | 523 tok/s | us-central1 |
| Nemotron-3-Super-120b-a12b | 0.30 | 0.90 | 127 tok/s | us-central1 |
| Nemotron-3.5-Lightning | 0.06 | 0.24 | 314.12 tok/s | eu-north1 |
| Nemotron-3-Nano-30B-A3B | 0.06 | 0.24 | 60 tok/s | eu-north1 |

Observations to confirm by measurement: Lightning costs the same as Nano and is listed about 5x faster. Super is cheaper than Ultra but listed slower; Ultra at 523 tok/s versus Super at 127 tok/s is an odd ordering for the larger model. The first smoke test (2026-10-13) did not reproduce the listed speeds, but its outputs were short; a long-output test is needed (see HARNESS_RESEARCH.md). Only Nano's card mentions multilingual support, so output quality of Lightning in non-English languages must be checked early.

### Estimate of one run (assumed volumes, not measured)

Every token volume below is assumed by the author, not measured. Costs are arithmetic on those volumes and the prices above: count x (input tokens x input price + output tokens x output price) / 1,000,000. They ignore caching, retries and reasoning overhead.

Assumption to replace with measurements: the assumed output volumes ignore reasoning tokens. In the smoke test, reasoning tokens appear to count inside `completion_tokens` (see HARNESS_RESEARCH.md), so real output, cost and rate-limit use may be higher than below.

Config B, hierarchy with a different model per level:

| Role | Count | Tokens per agent (in / out) | Arithmetic | USD |
|---|---|---|---|---|
| Director (Ultra) | 1 | 40,000 / 8,000 | 1 x (40,000 x 1.00 + 8,000 x 3.00) / 1M | 0.0640 |
| Managers (Super) | 5 | 20,000 / 4,000 | 5 x (20,000 x 0.30 + 4,000 x 0.90) / 1M | 0.0480 |
| Operators (Lightning) | 20 | 10,000 / 2,000 | 20 x (10,000 x 0.06 + 2,000 x 0.24) / 1M | 0.0216 |
| Auditor (Ultra) | 1 | 30,000 / 3,000 | 1 x (30,000 x 1.00 + 3,000 x 3.00) / 1M | 0.0390 |
| Total | 27 calls | 370,000 / 71,000 (441,000 tokens) | | 0.1726 |

In theory about 150 runs of B fit in the USD 26 of credits (26 / 0.1726 = 150.6), before retries and Tavily.

Config A2, the same hierarchy and volumes with every agent on Ultra: director 0.0640 + managers 5 x (20,000 x 1.00 + 4,000 x 3.00) / 1M = 0.1600 + operators 20 x (10,000 x 1.00 + 2,000 x 3.00) / 1M = 0.3200 + auditor 0.0390 = USD 0.5830 per run. Equivalently, 370,000 x 1.00 / 1M + 71,000 x 3.00 / 1M = 0.370 + 0.213 = 0.583. This is the "same volume entirely on Ultra" figure (about USD 0.58), so it corresponds to A2, not to A. On these assumptions A2 costs 0.5830 / 0.1726 = 3.4x B.

Config C, B plus a board and a VP. The extra volume is a placeholder assumption until the board is built: one more director with the same volume as the first (a board of two), and a VP on Ultra at 30,000 in / 6,000 out. Managers, operators and auditor are unchanged.

| Role | Count | Tokens per agent (in / out) | Arithmetic | USD |
|---|---|---|---|---|
| Directors (Ultra) | 2 | 40,000 / 8,000 | 2 x (40,000 x 1.00 + 8,000 x 3.00) / 1M | 0.1280 |
| VP (Ultra) | 1 | 30,000 / 6,000 | 1 x (30,000 x 1.00 + 6,000 x 3.00) / 1M | 0.0480 |
| Managers, operators, auditor | 26 | as in B | 0.0480 + 0.0216 + 0.0390 | 0.1086 |
| Total | 29 calls | 440,000 / 85,000 (525,000 tokens) | | 0.2846 |

Config A, a single Ultra agent with no hierarchy, has no estimate until it is measured. Its token volume does not follow from the hierarchy volumes above.

### Rate-limit implication (lower bound, per model)

Per-model limits for this account, read from the `x-ratelimit-*` response headers on 2026-10-13 and stored in `config/rate_limits.json` (see HARNESS_RESEARCH.md). They may change with dynamic scaling.

| Model | Requests per minute | Tokens per minute |
|---|---|---|
| Ultra | 300 | 200,000 |
| Super | 300 | 200,000 |
| Lightning | 600 | 400,000 |
| Nano | 100 | 800,000 |

Benchmark tokens per model for A2, B and C, from the assumed volumes in "Estimate of one run" (tokens = input + output per agent, 9 runs per configuration):

- Ultra. B: director 40,000 + 8,000 = 48,000 and auditor 30,000 + 3,000 = 33,000, so 81,000 per run. A2: every agent, 441,000 per run. C: two directors 2 x 48,000 = 96,000, VP 30,000 + 6,000 = 36,000 and auditor 33,000, so 165,000 per run. Total 9 x 81,000 + 9 x 441,000 + 9 x 165,000 = 729,000 + 3,969,000 + 1,485,000 = 6,183,000 tokens. At 200,000 TPM: 6,183,000 / 200,000 = 30.9 minutes.
- Super (managers in B and C): 5 x (20,000 + 4,000) = 120,000 per run. Total 18 x 120,000 = 2,160,000 tokens. At 200,000 TPM: 2,160,000 / 200,000 = 10.8 minutes.
- Lightning (operators in B and C): 20 x (10,000 + 2,000) = 240,000 per run. Total 18 x 240,000 = 4,320,000 tokens. At 400,000 TPM: 4,320,000 / 400,000 = 10.8 minutes.
- Nano: not used by any configuration.
- Requests: Ultra 9 x (2 + 27 + 4) = 297 at 300 RPM = 1.0 minute; Super 18 x 5 = 90 at 300 RPM = 0.3 minutes; Lightning 18 x 20 = 360 at 600 RPM = 0.6 minutes. Tokens per minute, not requests per minute, is the binding limit.

So the benchmark needs at least 30.9 minutes on Ultra alone, and Ultra is the bottleneck. Config A is not included (no estimate until measured). This is a lower bound. It assumes the limits are independent per model and that the token limit counts input plus output tokens (both UNVERIFIED), and it uses the assumed token volumes, which ignore reasoning tokens. The documented dynamic scaling (x1.2 for the next 15-minute window at 80% usage or more) may raise the limits during a long benchmark. Do not plan on it.

## Failures and loops

| Situation | Action |
|---|---|
| Output does not match schema | Same operator retries, max 2 |
| Operator keeps failing | Manager reassigns to another operator |
| Manager fails | Escalate to director |
| Level budget exhausted | Administrator stops it, manager returns partial result |
| Loop (repeated messages, no progress) | Automatic stop, escalate one level up |
| HTTP 429 | Wait for `Retry-After`, then retry with growing backoff |
| `finish_reason: "length"` | Treat as a failure: retry within limits with a larger `max_tokens` or reasoning off; charge every attempt |
| Auditor rejects | One correction cycle, then deliver with a visible warning |
| User pauses or cancels | Administrator freezes pending calls |

## Board and vice president

Optional, turned on by the user for many tasks. Several directors work at the same time, each with a block and a sub-budget. The VP exists only with a board: it is the only voice toward the user and splits tasks among directors. The user chairs everything. The board reduces time, not cost; extra coordination cost is shown separately. Provider rate limits may cap the benefit.

## Review at each level

Operator: schema validation by code. Manager: coherence and per-task criteria. Director: result versus goal and budget. Auditor: fixed rubric, separate context. User: final approval.

## Delivery package

Director (or VP) summary, deliverables, predicted versus real cost report, log of contracts and decisions, auditor verdict.

## Evaluation and benchmark

Metrics: cost per accepted deliverable, cost prediction error (real minus predicted, over predicted), time versus sequential, retry rate, auditor acceptance.

Configurations:

| Config | Setup | What it shows |
|---|---|---|
| A | A single Ultra agent, no hierarchy | What a user would do naively |
| A2 | The same hierarchy as B, every agent on Ultra | Isolates the effect of per-level model choice |
| B | Hierarchy with a different model per level | The proposed design |
| C | B plus board and VP | Time saved by the board, and its coordination cost |

The thesis (a different model per level costs less, at comparable quality) is tested by B versus A2, which differ only in the models. A versus B is the practical comparison against a naive single agent.

Design: 4 configurations x 3 cases x 3 repetitions = 36 runs, 9 per configuration.

Estimated cost, based on the assumed volumes in "Estimate of one run" (not measured), before retries and Tavily:

| Config | Runs | USD per run | USD total | Tokens total |
|---|---|---|---|---|
| A | 9 | not estimated until measured | unknown | unknown |
| A2 | 9 | 0.5830 | 9 x 0.5830 = 5.2470 | 9 x 441,000 = 3,969,000 |
| B | 9 | 0.1726 | 9 x 0.1726 = 1.5534 | 9 x 441,000 = 3,969,000 |
| C | 9 | 0.2846 | 9 x 0.2846 = 2.5614 | 9 x 525,000 = 4,725,000 |
| A2 + B + C | 27 | | 5.2470 + 1.5534 + 2.5614 = 9.3618 | 12,663,000 |

Budget to compare against: USD 26 of credits (25 event credit plus 1 account credit). After the 27 estimated runs, 26 - 9.3618 = USD 16.64 remains for the 9 runs of A, retries, development runs, the smoke test and the public live mode. If nothing else were spent, A could cost up to 16.6382 / 9 = USD 1.85 per run before the credits run out. That is a ceiling, not an estimate. Tavily is billed by Tavily, not from these credits. The real figures are set after the first measured run of each configuration.

Known limitation: the auditor is a model and may favor outputs similar to its own. Mitigation: fixed rubric, separate context, human review of a sample.

## Demo cases

Three simulated microbusiness cases written by the team and declared as simulated (initial proposal: beauty salon, corner grocery, workshop; the market is global, not tied to one country). Processes: basic digital presence (research with Tavily and a published site), customer replies, simple sales and expense tracking. Project material is in English; deliverables for a business may need another language, so each package includes an English summary.

Market evidence: public statistics on micro and small businesses from international sources (World Bank, OECD) still need to be collected and verified. Do not quote figures that have not been checked against the original publication.

## Interface and deployment

Chat with the director (or VP), live feed of hires and tasks, live org chart, budget panel (predicted versus real), delivery package view. Site and chat are built with GLM in `web/`. Deployment on Vercel with two modes: recorded (saved runs, no cost) and live (spending cap and per-visitor limit). Keys in environment variables only.

## Vision

A cost and quality governance layer for agent teams. The catalog is model-independent. Next step after this submission: add proprietary models such as Kosmo (in development, not included here).

## Schedule (3 h/day, Oct 12 to 29, 54 h)

| Phase | Dates | Hours | Deliverable |
|---|---|---|---|
| 1. Foundations | Oct 12 to 14 | 9 | Repo, credits, console prices, Tavily key, schemas, ledger skeleton, harness research |
| 2. Core | Oct 15 to 19 | 15 | Administrator layer, harness, catalog, store. One end-to-end run |
| 3. Agents and interface | Oct 20 to 24 | 15 | Full agents with Tavily, retries, reputation, chat and feed, deployed URL |
| 4. Board and evidence | Oct 25 to 27 | 9 | Board and VP, cost panel, 36-run benchmark, one good run for the video |
| 5. Submission | Oct 28 and 29 | 6 | Video, README, feedback, Devpost on the night of Oct 29 |

README is written at the end (Phase 5).

## Open decisions

Whether reasoning tokens are billed as output (compare with the console balance); caching under other conditions; long-output speed per model; what the token rate limit counts and whether limits are independent per model; reputation formula; store choice (Supabase or SQLite); scope of the public live mode; final demo cases.
