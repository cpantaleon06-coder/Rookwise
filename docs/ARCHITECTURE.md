# Rookwise: Architecture

Source of truth for humans and coding agents (Claude Code, GLM). Version of October 12, 2026.
Hackathon: Nebius x NVIDIA Global AI Hackathon 2026, track Best Apps and Agents. Submission deadline: October 30, 2026, 10:00 AM PDT.

## Rules for any agent working in this repo

- Write all code, comments, docs and UI text in English.
- Never commit secrets. Keys live in `.env` (see `.env.example`). Never print a key.
- Prices are never hard-coded. Read them from `config/prices.json`.
- Do not assume API details. Check `docs/HARNESS_RESEARCH.md` first and mark anything unverified as such.
- Every module in `core/` ships with tests in `tests/`.
- Ownership: `core/` is built with Claude Code. `web/` is built with GLM. They only talk through the API described in `docs/api.md` (written by Claude Code before the web UI starts).
- Report results exactly as measured. Do not invent numbers.

## Summary

A hierarchical team of AI agents with a controlled token budget. The user sets a goal and a spending cap. The system splits the goal, hires operators from a catalog with price, speed and reputation, runs them in parallel, audits the result, and returns a verifiable package showing real cost next to predicted cost.

Thesis to test with our own measurements: a hierarchy that uses a different model per level costs less than running the largest model for everything, with comparable quality according to an independent auditor. If the benchmark does not confirm it, we report what we measured.

Runs on NVIDIA Nemotron models on Nebius Token Factory. Demo cases are simulated and labeled as simulated. Kosmo (an in-house small language model under development) is a roadmap item and is not part of this submission.

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
- Record input and output tokens, model, cost and time of every call.
- Stop at a cap and return the partial result.
- Limit retries and concurrency (concurrency also respects the provider rate limits, see below).
- Honor the user's brake: pause, resume, cancel.

Cost of a call = input_tokens x price_in + output_tokens x price_out, with prices from `config/prices.json`.

## Harness (`core/harness/`)

The harness is the only code that talks to the model API. Agents are built on top of it and never call the API directly.

Responsibilities:
- Send chat completions to Token Factory and return text, tool calls and usage.
- Run the tool loop: model proposes `tool_calls`, harness executes them (for example Tavily search), appends `tool` messages, calls the model again, up to a step cap.
- Validate output against a schema (task_v1, result_v1) and retry within limits.
- Report usage to the administrator layer for every call.
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
  "output_tokens": 1900,
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

Observations to confirm by measurement: Lightning costs the same as Nano and is listed about 5x faster. Super is cheaper than Ultra but listed slower. Only Nano's card mentions multilingual support, so output quality of Lightning in non-English languages must be checked early.

Estimate of one run with token volumes assumed by the author (not measured):

| Role | Count | Tokens per agent (in / out) | Cost |
|---|---|---|---|
| Director (Ultra) | 1 | 40,000 / 8,000 | USD 0.064 |
| Managers (Super) | 5 | 20,000 / 4,000 | USD 0.048 |
| Operators (Lightning) | 20 | 10,000 / 2,000 | USD 0.0216 |
| Auditor (Ultra) | 1 | 30,000 / 3,000 | USD 0.039 |
| Total | | 370,000 in / 71,000 out | USD 0.1726 |

About 145 runs on USD 25 in theory, before retries and Tavily. The same volume entirely on Ultra would be about USD 0.58 (arithmetic on assumed volumes, not a measurement).

### Rate-limit implication (from the Token Factory docs, see HARNESS_RESEARCH.md)

The docs give an example baseline of 60 RPM and 400,000 TPM and say real defaults are in the console. If the console shows the same numbers, one run of about 441,000 tokens already exceeds one minute of the example TPM budget, and the 27-run benchmark (about 11.9M tokens) needs at least 30 minutes of throughput. Tokens per minute, not requests per minute, is the likely binding limit. Check the real numbers in the console before designing the parallelism.

## Failures and loops

| Situation | Action |
|---|---|
| Output does not match schema | Same operator retries, max 2 |
| Operator keeps failing | Manager reassigns to another operator |
| Manager fails | Escalate to director |
| Level budget exhausted | Administrator stops it, manager returns partial result |
| Loop (repeated messages, no progress) | Automatic stop, escalate one level up |
| HTTP 429 | Wait for `Retry-After`, then retry with growing backoff |
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

Design: 3 cases x 3 configurations x 3 repetitions = 27 runs. A: every agent on Ultra, no hierarchy. B: hierarchy by levels. C: hierarchy with board. With assumed volumes this is roughly USD 9 before retries and Tavily; the real figure is set after the first run of each configuration.

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
| 4. Board and evidence | Oct 25 to 27 | 9 | Board and VP, cost panel, 27-run benchmark, one good run for the video |
| 5. Submission | Oct 28 and 29 | 6 | Video, README, feedback, Devpost on the night of Oct 29 |

README is written at the end (Phase 5).

## Open decisions

Exact Token Factory model IDs; real console rate limits; whether Nemotron models support tool calling and JSON schema output; reputation formula; store choice (Supabase or SQLite); scope of the public live mode; final demo cases.
