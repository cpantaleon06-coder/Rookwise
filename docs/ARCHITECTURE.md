# Rookwise: Architecture

Source of truth for humans and coding agents (Claude Code). Version of October 16, 2026.
Hackathon: Nebius x NVIDIA Global AI Hackathon 2026, track Best Apps and Agents. Submission deadline: October 30, 2026, 10:00 AM PDT.

## Rules for any agent working in this repo

- Write all code, comments, docs and UI text in English.
- Never expose keys. Keys live in `.env` (see `.env.example`) or in server-side environment variables. Never commit a key, never print it, never send it to the browser.
- Prices are never hard-coded. Read them from `config/prices.json`.
- Do not assume API details. Check `docs/HARNESS_RESEARCH.md` first and mark anything unverified as such.
- Every module in `core/` ships with tests in `tests/`.
- Ownership: `core/` and `web/` are both built with Claude Code (GLM is not available). They only talk through the API described in `docs/api.md` (written by Claude Code before the web UI starts).
- Report results exactly as measured. Do not invent numbers.

## Summary

A hierarchical team of AI agents with a controlled token budget. The user sets a goal and a spending cap. The system splits the goal, hires operators from a catalog with price, speed and reputation, runs them in parallel, audits the result, and returns a verifiable package showing real cost next to predicted cost.

Thesis to test with our own measurements: a hierarchy that uses a different model per level costs less than running the largest model for everything, with comparable quality according to an independent auditor. If the benchmark does not confirm it, we report what we measured.

Runs on NVIDIA Nemotron models on Nebius Token Factory. Demo cases are simulated and labeled as simulated. Kosmo (an in-house small language model under development) is a roadmap item and is not part of this submission.

## Hackathon requirements

Source: Devpost rules page, read on 2026-10-13 (summarized extract; re-read the original before submitting).
**Verify against the Devpost page before submitting:** https://nebiusglobalaihackathon.devpost.com/rules

| Requirement | How Rookwise meets it | Status |
|---|---|---|
| Nebius: a runtime call to the Token Factory inference API (or running on Nebius AI Cloud compute) | Every model call goes to the Token Factory API through the harness | In progress: runtime calls verified in the smoke test (2026-10-13); product runtime planned |
| At least one NVIDIA open source model | NVIDIA Nemotron at every level, which is stricter than the rule | In progress: Nemotron used in the smoke test; product runtime planned |
| A working demo, hosted application or test build, free and accessible for testing until the Judging Period ends (Dec 15, 2026) | `web/` deployed on Vercel; the run executor and the live event stream on a separate host, chosen after measuring a real run (see "Interface and deployment"). Recorded mode replays stored event logs and costs nothing, so the demo keeps working without credits. Check credit expiry and any free-tier pausing (hosting, database) before depending on them | Planned (Phase 3) |
| Video: under three minutes, public on YouTube, shows the project working, no unlicensed third-party trademarks or music | Demo video, target length 2:45 | Planned (Phase 5) |
| Public repo with source code, assets and setup instructions | Public GitHub repo with source code; setup instructions go in the README | In progress: repo public with source code; setup instructions planned (Phase 5) |
| Open source license visible in the repository's About section | MIT `LICENSE` in the repo root; GitHub detects it as MIT (checked 2026-10-13) | Done |
| README with setup instructions that highlights how Nemotron and Token Factory were used | README written in Phase 5 | Planned (Phase 5) |
| Feedback on Nebius and NVIDIA tools | `FEEDBACK.md`, kept from day one | In progress |
| Track selection and a text description of features and functionality | Track: Best Apps and Agents. Description: Devpost text | Planned (Phase 5): track decided, description not written |
| Newly created or significantly updated after Aug 26, 2026 | Newly created: repo created 2026-10-12. The summary of significant updates only applies to pre-existing projects, so it does not apply here | Done |
| English, or English translations | All code, docs and UI text in English; business deliverables in other languages include an English summary | In progress |
| Optional: Best Use of Tavily bonus (USD 3,000), which requires a functional runtime call to the Tavily API as part of the solution. A project can win one Overall or one Track award, plus one Bonus | Researcher operators call Tavily search at runtime | Planned (Phase 3) |
| Judging stage one, pass/fail: fit with the theme and reasonable use of the required APIs | Token Factory and Nemotron at every level, Tavily at runtime | Planned |
| Judging stage two, four equally weighted criteria: Technological Implementation, Design, Potential Impact, Quality of the Idea | Implementation: budget ledger, harness, measured benchmark. Design: chat, live org chart, budget panel. Impact: cost governance for agent teams, microbusiness demo cases. Idea: a cost thesis measured, not assumed | Planned |
| Key dates: submission closes Oct 30, 2026, 10:00 am PT; judging Dec 1 to Dec 15, 2026; winners around Jan 11, 2027 | Submit on Devpost on the night of Oct 29 (Phase 5); keep the demo up through Dec 15 | Planned |

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
- Honor the user's brake: cancel. Pause and resume are planned; the API reserves them (HTTP 501) and the UI shows no pause or resume control until core supports them.

### Cost of a call

Prices come from `config/prices.json` in USD per 1M tokens, so each product below is divided by 1,000,000.

```
cost = (input_tokens - cached_tokens) x price_in
     + cached_tokens x price_cached_in
     + output_tokens x price_out
```

- `input_tokens` is `usage.prompt_tokens`. `cached_tokens` is `usage.prompt_tokens_details.cached_tokens` (VERIFIED as a field in the docs); treat a missing value as 0. Whether Token Factory reports non-zero cached tokens for Nemotron is UNVERIFIED.
- `price_cached_in` is the optional `cached_input` price per model in `config/prices.json`. It is `null` for every model because no cached price is published in what we have. When it is `null`, the ledger uses `price_in` for cached tokens and says so: the ledger entry carries `"cached_price_fallback": true`.
- `output_tokens` is `usage.completion_tokens`. VERIFIED (2026-10-16, Stage 2 Task 0, from the saved streaming probe data; see "Reasoning token accounting" in `docs/HARNESS_RESEARCH.md`): `completion_tokens` already includes the reasoning tokens (`usage.completion_tokens_details.reasoning_tokens`) on all four models, so reasoning is billed once, as part of `output_tokens`. As a safeguard, if a response ever reports more reasoning tokens than completion tokens, they are added to `output_tokens`; no observed call did. UNVERIFIED, pending a console check: whether Token Factory bills reasoning tokens at the output price.
- Money is `decimal.Decimal`, never float, and prices are parsed from the JSON text as Decimal. The formula is computed exactly; the ledger then holds whole micro-USD (USD 0.000001): reservations and charges round up, caps round down, predictions round to the nearest micro-USD. Rounding therefore never lets spend pass a cap, and every total is an exact sum. Spend can still pass a cap the way it could before: when a call's real usage is larger than its reservation (an input estimate that was too low), the charge is recorded and the scope stops.

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

Built so far (Stage 1, 2026-10-15): streaming calls with `stream_options.include_usage`, the reserve, charge and release cycle with the ledger, per-model limits on requests and tokens per minute plus a concurrency cap, bounded retries, cancellation, and record and replay of calls (`HARNESS_MODE`: live, record or replay). Settings and model quirks live in `config/harness.json`. When a stream ends or is cut without usage, the harness charges the full reservation and marks the usage estimated (`on_missing_usage`). The public surface is documented at the top of `core/harness/__init__.py`.

Built so far (Stage 2, 2026-10-16): native tool calls in the stream; the tool loop (`core/harness/loop.py`) with two protocols, `json_protocol` (the baseline) and `native_tools`, chosen per model in `config/harness.json` (native for Ultra, Super and Lightning, JSON actions for Nano, from the tool-calling probe); step, repeat, timeout, truncation and token limits; `finish_reason: "length"` discarded and retried once with a larger `max_tokens`, then treated as a failure; tool results in cassettes, so a full tool run replays offline; Tavily search (`core/tools/tavily.py`, query counts only, cost UNVERIFIED); final answer validation, up to two repairs with the validation errors, then the escalation ladder (Lightning or Nano to Super, Super to Ultra) under the ledger caps, with one record per attempt and the labels `first_pass_ok`, `ok_after_retry`, `ok_after_escalation` and `failed`; and `core/runner.py` (`run_operator`, one task_v1 for one catalog operator, no hierarchy). The loop protocols are described in `core/harness/README.md`. Not built yet: reading `x-ratelimit-*` headers, the hierarchy (director, managers, auditor) and the server.

Built so far (2026-10-17): money is `decimal.Decimal` end to end (`core/money.py`): prices parsed from the JSON text, the ledger's reservations, charges, caps, predictions and totals in whole micro-USD (rounding rules in "Cost of a call"), the harness's charges and attempt records, task_v1 budgets, result_v1 usage and the catalog price. A float passed to the ledger raises TypeError and a float in any contract model fails validation. The API contract sends money as six-decimal strings (docs/api.md, "Conventions"), with regenerated schemas and fixtures.

## Operator catalog

Each operator is a catalog entry with role, model, price estimate, latency, reputation, tools, skills and schemas. `skills` lists the ids of the Nemotron-adapted skills composed into the operator's system prompt; `config/skills.json` maps each role to its skills.

```json
{
  "operator_id": "researcher-lightning-01",
  "role": "researcher",
  "model": "nemotron-3.5-lightning",
  "price_per_task_est_usd": "0.002000",
  "avg_latency_s": 8,
  "reputation": 0.82,
  "tools": ["tavily_search"],
  "skills": ["prose-style"],
  "input_schema": "task_v1",
  "output_schema": "result_v1"
}
```

Selection: lowest expected cost that meets a minimum reputation and maximum latency. Reputation is a moving average of auditor acceptance. All numbers above are placeholders until measured.

## Skills layer (Nemotron-adapted)

Operators and the auditor receive role-specific instructions called skills. Each skill is a short text in `skills/<id>/SKILL.md`, adapted for Nemotron with reasoning off and JSON output. Its frontmatter names the source, the version or commit, the license, the copyright holder, the roles it serves and the changes made. `THIRD_PARTY_NOTICES.md` and `licenses/` carry the attribution.

- `config/skills.json` maps each role to its model and skills, and sets a token ceiling per skill and per role.
- `core/skills` validates each skill and composes a role's system prompt the same way every time: the base prompt first, then the role's skills in config order. It returns the text and the skill ids; the harness records the ids in the ledger entry (`skills`). It refuses to compose when a ceiling would be passed.
- Token counts come from measurement. `scripts/skill_check.py` measures each skill's prompt-token cost on its role's model (prompt tokens with the skill minus without). A measurement counts only while its SHA-256 matches the skill text; after an edit, the loader falls back to characters / 4 and labels the count an estimate.
- Measured on 2026-10-15: 205 to 656 prompt tokens per skill (see "Skills on Nemotron" in `docs/HARNESS_RESEARCH.md`). At Lightning's input price that adds at most 656 x 0.06 / 1M = USD 0.0000394 per call; at Ultra's, 656 x 1.00 / 1M = USD 0.000656.
- Skills: `prose-style` (copywriter, researcher, and the auditor's rubric), `minimal-code` (coder), `code-review`, `testing-strategy`, `debug` and `deploy-checklist` (reviewer roles), and `incident-triage`, `status-update` and `postmortem` (ITOps roles, placeholders until the ITOps and DevOps use case is final). Demo incident data is simulated and labeled as simulated.
- Each skill ends with a rule that keeps the output format the task requires, so the harness's JSON schema stays in charge of the format.
- The Claude Code plugins in `.claude/` stay development tools. The runtime reads only the adapted copies in `skills/` (see `docs/PLUGINS.md`).

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
  "budget": {"max_input_tokens": 12000, "max_output_tokens": 2500, "max_usd": "0.004000"},
  "deadline_s": 60
}

// result_v1 (operator to manager)
{
  "task_id": "t-014",
  "status": "ok",
  "output_ref": "store://r-003/results/t-014",
  "usage": {"input_tokens": 9800, "output_tokens": 1900, "usd": "0.001050"},
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
  "usd_real": "0.001050",
  "usd_predicted": "0.001200",
  "ts": "2026-10-20T15:02:11Z",
  "usage_estimated": false
}
```

Contract change on 2026-10-16: `ledger_entry` gained `usage_estimated` (boolean, default false). It is true when the API sent no usage and the harness charged under `on_missing_usage` in `config/harness.json` (the full reservation by default), so estimated charges stay visible in the ledger. The contracts carry no version number (`task_v1` and `result_v1` are unchanged); a reader that does not know the field can treat a missing value as false.

Contract change on 2026-10-17: every money field (`max_usd`, `usd`, `usd_real`, `usd_predicted`, `price_per_task_est_usd`) is a decimal string with exactly six decimals (micro-USD), as in the examples above, never a JSON number. In Python it is `decimal.Decimal` (`core/money.py`); a float is refused.

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

Model ladder (proposed, pending the user's decision, not final): escalation runs inside the operator runner as a mechanical retry. After the repairs above, the same task moves up the model ladder in `config/harness.json` (Lightning or Nano to Super, Super to Ultra) under the ledger caps. A manager reassigns the task to another operator only after the ladder is exhausted.

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

Chat with the director (or VP), live feed of hires and tasks, live org chart, budget panel (predicted versus real), delivery package view. Site and chat are built with Claude Code in `web/`. The API between `core/` and `web/` is [docs/api.md](api.md) (v1: decided for visitors, modes, refusals, hosting, ids and money; the rest is draft, frontend may start), with JSON Schemas in `docs/api/schemas/` (what the frontend consumes), synthetic fixtures in `examples/api/` and a mock server described in [docs/api-mock.md](api-mock.md).

Deployment (decided 2026-10-16, see [docs/DECISIONS.md](DECISIONS.md)):

- The web app runs on Vercel. The run executor and the live event stream run on a separate host, chosen after measuring how long a real run takes (not measured yet). VERIFIED from the Vercel docs: with Fluid compute a Vercel Function stops at 300 s on Hobby and at 800 s on Pro, streamed responses included (details in docs/api.md, "Hosting"). The API stays host-agnostic, with `Last-Event-ID` resume for reconnects.
- Recorded mode replays the stored event log of an earlier run, with its original event ids and delays, at no cost. Recorded runs are labelled as recorded in every API payload and on screen. Which real run becomes the recorded demo is chosen after the benchmark.
- Live mode makes real calls under three limits from `.env.example`: USD per run (`LIVE_DEMO_MAX_USD_PER_RUN`), USD per day for the whole deployment (`LIVE_DEMO_MAX_USD_PER_DAY`), and one live run per visitor per day (`LIVE_DEMO_MAX_RUNS_PER_VISITOR_PER_DAY`). A visitor is a signed, anonymous, HttpOnly cookie. A visitor can clear cookies, so the two USD caps are the limit that cannot be bypassed.
- A refused live request stays refused (HTTP 429 for the daily cap and the visitor limit). The UI offers a recorded run as an explicit choice; the server never falls back on its own.
- Keys in environment variables only.

## Vision

A cost and quality governance layer for agent teams. The catalog is model-independent. Next step after this submission: add proprietary models such as Kosmo (in development, not included here).

## Development toolchain (Claude Code plugins)

Rookwise is built with Claude Code and a small set of plugins and skills: stop-slop for human-facing text, ponytail as a guard against over-building in `core/`, harness-engineering as a Claude Code workflow that plans the work, builds it in stages and checks the result, and the engineering and incident.io plugins from the user's account. They run at development time only. The Rookwise runtime (`core/`, Nemotron on Nebius Token Factory) must not depend on any of them, and their cost comes from the Claude plan, not from the Nebius credits. The runtime uses adapted, attributed copies of four of them in `skills/` (see "Skills layer"). harness-engineering is a development workflow and is not the Rookwise harness in `core/harness/`. Setup, pinned versions, licenses, per-tool rules and the boundary are in [docs/PLUGINS.md](PLUGINS.md).

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

Whether Token Factory bills reasoning tokens at the output price (compare with the console balance); caching under other conditions; long-output speed per model; what the token rate limit counts and whether limits are independent per model; reputation formula; store choice (Supabase or SQLite); the host for the run executor and the live stream (after measuring a real run); which real run becomes the recorded demo, and whether demo recordings are committed; Nano's tool protocol (revisit after the benchmark); the model ladder inside the runner versus reassignment by a manager (proposed, pending); the ITOps and DevOps domain and the final demo cases. The scope of the public live mode is decided. Decisions and their reasons are logged in [docs/DECISIONS.md](DECISIONS.md).
