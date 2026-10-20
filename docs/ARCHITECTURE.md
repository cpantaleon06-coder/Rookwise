# Rookwise: Architecture

Source of truth for humans and coding agents (Claude Code). Version of October 17, 2026.
Hackathon: Nebius x NVIDIA Global AI Hackathon 2026. Submission deadline: October 30, 2026, 10:00 AM PDT; we submit on the night of October 29. Devpost track: not decided (Best Apps and Agents, or Coding and Agentic Engineering; see docs/DECISIONS.md, "Still open").

## Rules for any agent working in this repo

- Write all code, comments, docs and UI text in English. No em dashes in documents; use parentheses.
- Never expose keys. Keys live in `.env` (see `.env.example`) or in server-side environment variables. Never commit a key, never print it, never send it to the browser.
- Prices are never hard-coded. Read them from `config/prices.json`.
- Do not assume API details. Check `docs/HARNESS_RESEARCH.md` first and mark anything unverified as such.
- Every module in `core/` ships with tests in `tests/`.
- Ownership: `core/` and `web/` are both built with Claude Code. They only talk through the API described in `docs/api.md`.
- Test data is synthetic and says so in every file. No real hostnames, keys or people.
- Report results exactly as measured. Do not invent numbers.

## Value proposition and target user

Rookwise investigates operational incidents for small teams without a dedicated SRE, under a hard budget the user sets.

The user: a team of a few engineers that runs its own services and carries the pager itself. When something breaks at 3 a.m., nobody on the team has the time to read 20,000 log lines across three services. Agents could read them, but the team has two reasons not to trust them:

1. Trust. An agent can state a root cause with confidence and cite log lines that do not exist. The team cannot check every claim at 3 a.m.
2. Cost. An agent run has no price tag up front. The bill arrives after the run, and a long investigation on a large model can cost more than the team expects.

What Rookwise offers against each:

- Every claim in a diagnosis cites a source and line numbers, and deterministic code (not a model) checks that the quoted text is really there. Claims that fail the check are shown as unsupported, never hidden.
- The user sets a hard budget before the run. The ledger reserves money before every model call and refuses calls that do not fit, so the run cannot pass the cap through rounding or retries. Every run reports predicted versus real cost.
- Cheap models read the volume (logs and metrics), a strong model judges, an independent auditor checks the result, and a human approves before anything happens. In v1 nothing is executed at all.
- Accuracy is measured, not claimed: a benchmark of simulated incidents with known root causes scores every configuration (see "Benchmark design").

The engine is domain-neutral. Roles, skills and evidence bundles are data, so the same code runs two other domains as generality proofs (see "Proof domains").

## What Rookwise does, end to end

1. Intake. An alert or ticket starts the investigation. The user picks the incident's evidence (logs, metrics, the recent deploy diff, the runbook) and sets the USD cap.
2. Budget. The administrator layer opens the run in the ledger with that cap.
3. Plan. The director (the strong model) reads the ticket, the runbook and a short inventory of the sources, then plans the investigation: which sources to read, split into tasks for operators, grouped into blocks for managers.
4. Read. Operators (cheap models) each read one slice of the evidence and return findings: short claims, each with citations (source id, first and last line, exact quote). Operators may search error signatures and advisories with Tavily.
5. Consolidate. Each manager merges its operators' findings for its block.
6. Judge. The director turns the findings into a diagnosis: root cause, a root-cause category, the claims that support it (with the ids of those the root cause rests on), and a proposed remediation plan (steps with action, why, risk and reversible).
7. Verify. `core/evidence.py` checks every citation of every claim of the diagnosis against the evidence. Unsupported claims are withdrawn from the diagnosis with their reason codes and stay listed (D3).
8. Audit. If every root-cause claim was withdrawn, or no supported claim remains, the diagnosis is inconclusive and the auditor makes no model call. Otherwise the independent auditor (a separate context and prompt) reviews the supported claims, sees the withdrawn list with its reasons, and judges against its rubric.
9. Approve. The human reads the diagnosis, the evidence check, the audit and the cost report, and approves or rejects the remediation plan. In v1 approving only records the decision.
10. Close. The ledger closes; the run's package keeps the diagnosis, the evidence check, the audit, the decision and predicted versus real cost.

Steps 3 to 8 run today as the `core/team` skeleton on stubs, with source slicing (each operator reads one slice), the director's diagnosis and the withdrawal of unsupported claims; the approval of the remediation is not built yet (see "Built so far").

## Roles and levels

| Level | Role | Model (proposed) |
|---|---|---|
| Human | Sets the cap and the evidence, reads the result, approves or rejects the remediation plan | n/a |
| Director | Plans the investigation, writes the diagnosis and the remediation plan. The only agent that talks to the user | Ultra |
| Managers | Own one block of the plan, give its tasks to operators, consolidate their findings | Super (Lightning to be tested) |
| Operators | Read one slice of the evidence, one task at a time, and return cited findings | Lightning (Super for hard tasks) |
| Independent auditor | Reviews the diagnosis in a separate context, after the deterministic evidence check | Ultra, different prompt and context |
| Administrator layer (the ledger) | Budget, caps, sub-budgets, retries, concurrency | Deterministic code, no model |
| Evidence check | Verifies every citation | Deterministic code (`core/evidence.py`), no model |
| Harness | The only code that calls the model API; runs tools, validates output, reports usage | Code, no model |

Communication is vertical. Operators talk to their manager, managers to the director, and only the director talks to the user. Roles, their model alias and their skills are data in `config/skills.json` (the director, manager and auditor roles carry a `level`); the operators come from the operator catalog.

## The human approval gate

v1 is read-only. Rookwise investigates and proposes a remediation plan; the human approves or rejects it; approving records the decision in the run and executes nothing. Rookwise has no credentials for the user's systems and no tool that changes them.

The API contract today has one approval: `POST /runs/{run_id}/approval`, while a run is `awaiting_approval`, which approves the investigation plan before the operators start (docs/api.md). The approval of the remediation plan at the end of a run is not in the contract yet; it needs a contract change before the web app builds it.

## The evidence rule

Every claim cites its evidence: a source id, the first and last line (1-based) and a quote copied from those lines. `core/evidence.py` checks each citation with no model and no network:

- the source exists (`source_missing` otherwise);
- the line range is inside the source (`line_out_of_range`);
- the quote appears in the cited lines after whitespace normalization only, with no case folding and no fuzzy matching (`quote_not_found`).

Agents write citations with exactly four fields (`source_id`, `line_start`, `line_end`, `quote`), and the quote must be a single line. A quote with a line break fails the agent's output schema (`SourceCitation` in `core/team/models.py`), so the harness asks for a repair, which counts toward the repair limit, instead of the quote failing later in the evidence check. Each run also gives its operators a run-bound output model (`findings_model(bundle)`, same name and JSON Schema as `Findings`) that checks every quote against the run's sources: the whitespace-normalized quote must be part of one source line inside the cited range. A quote that needs several lines, or joins lines with a separator such as " | ", fails as a repairable error too, and so does a quote that is in no line at all. The evidence check itself is unchanged and still runs in the audit; the claims that now reach it unsupported are the ones without citations. In the first live run, 9 of 22 citations failed because their quotes ran over several lines (a format problem, not fabrication).

A claim is supported only when it has at least one citation and every citation is valid; a claim with none is `no_citations`. Unsupported claims are never dropped or hidden. Since 2026-10-19 (D3, `core/team/auditor.py`):

- After the deterministic check, every unsupported claim of the diagnosis moves from `claims` to `withdrawn_claims`, with its reason code and the reason of each of its citations. The result, the audit and the director's closing message list them.
- If every claim in `root_cause_claim_ids` was withdrawn, or no supported claim remains (or there is no diagnosis at all), the status is `inconclusive`: the auditor makes no model call and the result says inconclusive. API contract v1 has no inconclusive verdict, so the `audit_result` event carries verdict `rejected`, a failed check "The diagnosis rests on supported claims" and a warning that starts with "Inconclusive".
- Otherwise the status is `audited`: the auditor model receives the supported claims, the withdrawn list with its reasons, its rubric and the cited lines (with two lines of context, not the whole bundle). An accepted diagnosis with withdrawn claims is `accepted_with_warning`.
- The run result counts the supported claims, the withdrawn claims and the withdrawn claims per reason code. The operators' claims are checked too and reported apart (`operator_evidence`).

The operators' run-bound output model still rejects a reply with a wrong quote, so the operator repairs it. The director's diagnosis is validated for shape only (the schema with its one-line quote, the category enum and the claim ids), so a wrong quote in it reaches the deterministic check and its claim is withdrawn with the reason code (`quote_not_found`, `line_out_of_range`, `source_missing` or `no_citations`). If every root-cause claim is withdrawn, the director gets exactly one targeted repair request: it lists those claims with their reason codes and the lines around what they cite, and asks for corrected citations (ledger task `diagnosis-repair`). If the repaired diagnosis still has no supported root-cause claim, the result is inconclusive. The citation log records the director's first reply and the reply after the repair.

## Budget and cost reporting

### Administrator layer (deterministic code)

- Reserve budget before each call, charge real cost after.
- Caps per run, per level and per task, and sub-budgets as ledger allocations: the managers' and the auditor's allocations are held out of the run, each operator's out of its manager's; an agent's calls are drawn from its allocation, and closing it gives the unspent part back to the parent.
- Record input, cached, output and reasoning tokens, model, cost and time of every call.
- Stop at a cap and return the partial result.
- Limit retries and concurrency. Rate limiting and concurrency are per model and read from `config/rate_limits.json`. The administrator enforces requests per minute and tokens per minute for each model before reserving a call.
- Honor the user's brake: cancel. Pause and resume are planned; the API reserves them (HTTP 501) and the UI shows no pause or resume control until core supports them.

How the run budget is split (the auditor's share first, then one equal allocation per block, then per operator task) is `BudgetPolicy` in `core/team/config.py`. Its shares are placeholders, not measured.

### Cost of a call

Prices come from `config/prices.json` in USD per 1M tokens, so each product below is divided by 1,000,000.

```
cost = (input_tokens - cached_tokens) x price_in
     + cached_tokens x price_cached_in
     + output_tokens x price_out
```

- `input_tokens` is `usage.prompt_tokens`. `cached_tokens` is `usage.prompt_tokens_details.cached_tokens` (VERIFIED as a field in the docs); treat a missing value as 0. Whether Token Factory reports non-zero cached tokens for Nemotron is UNVERIFIED.
- `price_cached_in` is the optional `cached_input` price per model in `config/prices.json`. It is `null` for every model because no cached price is published in what we have. When it is `null`, the ledger uses `price_in` for cached tokens and says so: the ledger entry carries `"cached_price_fallback": true`.
- `output_tokens` is `usage.completion_tokens`. VERIFIED (2026-10-16, from the saved streaming probe data; see "Reasoning token accounting" in `docs/HARNESS_RESEARCH.md`): `completion_tokens` already includes the reasoning tokens on all four models, so reasoning is billed once, as part of `output_tokens`. As a safeguard, if a response ever reports more reasoning tokens than completion tokens, they are added to `output_tokens`; no observed call did. UNVERIFIED, pending a console check: whether Token Factory bills reasoning tokens at the output price.
- Money is `decimal.Decimal`, never float, and prices are parsed from the JSON text as Decimal. The formula is computed exactly; the ledger then holds whole micro-USD (USD 0.000001): reservations and charges round up, caps round down, predictions round to the nearest micro-USD. Rounding therefore never lets spend pass a cap, and every total is an exact sum. Spend can still pass a cap when a call's real usage is larger than its reservation (an input estimate that was too low): the charge is recorded and the scope stops.
- Worked examples (the ledger tests use them): 40,000 input and 8,000 output tokens on Ultra cost (40,000 x 1.00 + 8,000 x 3.00) / 1M = USD 0.064; 10,000 input and 2,000 output tokens on Lightning cost (10,000 x 0.06 + 2,000 x 0.24) / 1M = USD 0.00108, so 20 such calls cost USD 0.0216.

### What a run reports

Every run reports predicted versus real cost: per call, per level and for the run, with the prediction error (real minus predicted, over predicted) and the number of charges whose usage was estimated. The API sends money as six-decimal strings (docs/api.md, "Conventions"). The run's predicted cost is the sum of the predictions made before each call. The harness makes each call's prediction when the caller gives none: the input estimate without its headroom plus `prediction.output_fraction` of the call's `max_tokens` (0.5, a placeholder until runs calibrate it; config/harness.json), priced by the ledger. The ledger keeps it on every entry, and `RunReport` sums it for the run (`predicted_usd`) and per model (`by_model`), next to the real cost; `scripts/team_smoke.py` writes both into its run summary. How the director predicts a run's cost before it starts is not built yet.

## Harness (`core/harness/`)

The harness is the only code that talks to the model API. Agents are built on top of it and never call the API directly. A test (`tests/test_harness_boundary.py`) fails if any other module in `core/` reaches the model API or imports an HTTP client outside the allowlist.

Every model call is gated by the administrator layer. Before each call the harness asks it to reserve budget for that call (a worst-case estimate from the prompt size, `max_tokens` and the model's prices). After the call it reports the real usage, and the ledger charges the real cost and releases the rest of the reservation. No model call happens without a reservation; if the reservation is refused, the call is not made.

Responsibilities:
- Reserve budget with the administrator layer before every model call, and report real usage after it.
- Send chat completions to Token Factory and return text, tool calls and usage.
- Run the tool loop: the model proposes `tool_calls`, the harness executes them (for example Tavily search), appends `tool` messages and calls the model again, up to a step cap. Each step is a model call with its own reservation.
- Validate output against a schema (task_v1, result_v1 and each agent's output model) and repair within limits.
- Treat `finish_reason: "length"` as a failure, even when some content came back, and charge the call to the ledger. Every role has an output ceiling (`max_output_tokens` in config/skills.json); each call is sent with it and the ledger reserves it, so a `length` finish ends the attempt as a typed outcome and is not retried with the same ceiling.
- Choose the reasoning mode per call by role. Reasoning off is the starting default for operators, to be confirmed by the benchmark.
- Set `max_tokens` to cover reasoning plus the answer: reasoning tokens count inside `completion_tokens` and share the same `max_tokens` limit.
- Respect rate limits: honor `Retry-After` on HTTP 429 and back off. Reading `x-ratelimit-*` headers is not built yet.
- Record and replay: in record mode every model call and every tool result goes into a cassette; replay never calls the API or a tool.
- Model-agnostic interface: a model is a name, an endpoint, a price entry and a few flags.

What is verified and what is not is tracked in `docs/HARNESS_RESEARCH.md`. The loop protocols (`native_tools` for Ultra, Super and Lightning, `json_protocol` for Nano) are described in `core/harness/README.md`.

## Tavily use

Operators may call Tavily search at runtime to look up an error signature or a vendor advisory (for example the text of an exception, or a dependency version and "memory leak"). The tool is `core/tools/tavily.py`; it records query counts, not a dollar cost (Tavily's billing per query is UNVERIFIED). In record mode the harness stores every Tavily result in the run's cassette next to the model calls, so a recorded run replays with the same search results and the benchmark stays deterministic. A search result is not evidence: claims must still cite the incident's own sources, which the evidence check reads; a search can only point an operator to where to look.

## Operator catalog

Each operator is a catalog entry: role, model, a price estimate, a latency estimate, tools, skills and schemas. `skills` lists the ids of the Nemotron-adapted skills composed into the operator's system prompt; `config/skills.json` maps each role to its skills. The catalog is configuration, not a market: a manager takes the cheapest entry for the task's role and, if that operator fails, the next one.

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

`reputation` is a static field in the entry, used only to break ties between equally priced operators; no formula updates it (see "Scope cuts"). All numbers above are placeholders. The incident roles are `log-reader`, `metrics-reader` and `deploy-diff-reader` (Lightning, with the escalation ladder of `config/harness.json`), each with an original reading skill. The older ITOps roles in `config/skills.json` (`incident-triager`, `status-updater`, `postmortem-writer` and the others) stay as placeholders; the smoke scenario uses them.

## Skills layer (Nemotron-adapted)

Operators and the auditor receive role-specific instructions called skills. Each skill is a short text in `skills/<id>/SKILL.md`, adapted for Nemotron with reasoning off and JSON output. Its frontmatter names the source, the version or commit, the license, the copyright holder, the roles it serves and the changes made. `THIRD_PARTY_NOTICES.md` and `licenses/` carry the attribution of adapted skills. The three incident reading skills (`log-reading`, `metrics-reading`, `deploy-diff-reading`) are original (`source_url: original`, the repository's MIT license); they tell the operator to quote one verbatim line with its timestamp per citation, never join lines, report only what its slice shows, say so when the slice shows nothing relevant, and not rely on severity words.

- `config/skills.json` maps each role to its model and skills, and sets a token ceiling per skill and per role.
- `core/skills` composes a role's system prompt the same way every time: the base prompt first, then the role's skills in config order. The harness records the skill ids in each ledger entry (`skills`). Composition refuses to pass a ceiling.
- Token counts come from measurement. `scripts/skill_check.py` measures each skill's prompt-token cost on its role's model. A measurement counts only while its SHA-256 matches the skill text; after an edit, the loader falls back to characters / 4 and labels the count an estimate.
- Measured on 2026-10-15: 205 to 656 prompt tokens per skill (see "Skills on Nemotron" in `docs/HARNESS_RESEARCH.md`). At Lightning's input price that adds at most 656 x 0.06 / 1M = USD 0.0000394 per call; at Ultra's, 656 x 1.00 / 1M = USD 0.000656.
- Each skill ends with a rule that keeps the output format the task requires, so the harness's JSON schema stays in charge of the format.
- The Claude Code plugins in `.claude/` stay development tools. The runtime reads only the adapted copies in `skills/` (see `docs/PLUGINS.md`).

## Messages and shared store

Messages carry ids and references, not content. Content lives in the store (Supabase Postgres or SQLite; not decided, `InMemoryStore` today), behind one interface.

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

Contract changes: on 2026-10-16 `ledger_entry` gained `usage_estimated` (default false), true when the API sent no usage and the harness charged under `on_missing_usage` in `config/harness.json`. On 2026-10-17 every money field became a decimal string with exactly six decimals, as above; in Python it is `decimal.Decimal` (`core/money.py`) and a float is refused.

## Models, prices and rate limits

Prices and speeds from the Nebius console model cards, read October 12, 2026.

| Model | Input (USD / 1M) | Output (USD / 1M) | Listed speed | Region |
|---|---|---|---|---|
| Nemotron-3-Ultra-550b-a55b | 1.00 | 3.00 | 523 tok/s | us-central1 |
| Nemotron-3-Super-120b-a12b | 0.30 | 0.90 | 127 tok/s | us-central1 |
| Nemotron-3.5-Lightning | 0.06 | 0.24 | 314.12 tok/s | eu-north1 |
| Nemotron-3-Nano-30B-A3B | 0.06 | 0.24 | 60 tok/s | eu-north1 |

Ultra costs about 16.7 times Lightning per input token (1.00 / 0.06) and 12.5 times per output token (3.00 / 0.24). That gap is why cheap models read the volume. The listed speeds are not reproduced yet (see `docs/HARNESS_RESEARCH.md`, "Speed").

Per-model limits for this account, read from the `x-ratelimit-*` response headers on 2026-10-13 and stored in `config/rate_limits.json`. They may change with dynamic scaling.

| Model | Requests per minute | Tokens per minute |
|---|---|---|
| Ultra | 300 | 200,000 |
| Super | 300 | 200,000 |
| Lightning | 600 | 400,000 |
| Nano | 100 | 800,000 |

What the token limit counts (input plus output, or something else) and whether the limits are independent per model are UNVERIFIED. The context window of each model is not recorded in `docs/HARNESS_RESEARCH.md` and is UNVERIFIED.

## Failures and loops

| Situation | Action |
|---|---|
| Output does not match schema | Same operator retries, max 2 |
| Operator keeps failing | Manager reassigns to another operator |
| Task hits its own ceiling (`length` at its output ceiling, or `token_ceiling`) | At most one reassignment: the next catalog operator for the role, or the same operator one rung up the model ladder; then escalate to director |
| Manager fails | Escalate to director |
| Level budget exhausted (any ledger stop) | Administrator stops that scope and emits `budget_exhausted`; the task is not reassigned, manager returns partial result |
| Loop (repeated messages, no progress) | Automatic stop, escalate one level up |
| HTTP 429 | Wait for `Retry-After`, then retry with growing backoff |
| `finish_reason: "length"` | Treat as a failure, charge the call, end the attempt with the typed outcome `length`; no retry with the same ceiling |
| Auditor rejects | One correction cycle, then deliver with a visible warning (the correction cycle is not built) |
| User cancels | Administrator freezes pending calls |

Model ladder (proposed, pending the user's decision): after the repairs above, the same task moves up the model ladder in `config/harness.json` (Lightning or Nano to Super, Super to Ultra) under the ledger caps. A manager reassigns the task to another operator only after the ladder is exhausted. `core/team` follows this today.

## Benchmark design

The benchmark measures accuracy against known root causes and cost against the prediction. Its data is the simulated-incident corpus (`benchmarks/incidents/`, generated by `scripts/gen_incidents.py`), the single source of test data for the benchmark, the live runs and later experiments.

- Incidents: 6, split 3 dev and 3 test. Each split has three different root-cause categories, so the test set does not repeat a dev category. Prompts, skills and `BudgetPolicy` are tuned on dev only and frozen before the test runs.
- Configurations: (a) the full hierarchy (director, managers, operators, auditor, a model per level); (b) a single large model (Ultra) doing the whole investigation; (c) a single small model (Lightning) doing the whole investigation. (b) and (c) get the same evidence, the same output schema and the same evidence check, and read the evidence in slices made by the same slicer as (a) (D1, docs/DECISIONS.md).
- Caps per incident are config values per configuration (D2): USD 0.10 for (a), unmeasured and revisited after the first approved run on a dev incident; (b) and (c) run with a safety cap of USD 1.00 and report what it cost them to reach an answer.
- Repeats: 2 per incident and configuration, so 6 x 3 x 2 = 36 runs.
- Reporting: TEST incidents are reported separately from DEV. Dev numbers show tuning, not generalization.

Metrics, per run and aggregated per configuration:

| Metric | Definition |
|---|---|
| `diagnosis_correct` | The diagnosis's root-cause category matches the ground truth AND at least one essential evidence line is cited by a citation that passes the evidence check. This scoring rule is a proposal. |
| `citation_verified_rate` | Valid citations over all citations (`core/evidence.py`) |
| Citation first-pass validity | Valid citations over all citations in each task's first reply, before any repair (`TeamRun.citation_log`) |
| Citation repairs | Repair attempts spent on citation errors |
| Withdrawn claims | Claims of the diagnosis withdrawn as unsupported (D3); they never count toward `diagnosis_correct` or `evidence_recall` |
| `evidence_recall` | Essential evidence refs covered by at least one valid citation, over all essential refs. A valid citation covers a ref when its quote, inside its cited lines, falls on one of the ref's lines; a wide range whose quote comes from another line covers nothing |
| Cost | Predicted versus real USD, and the prediction error (real minus predicted, over predicted) |
| Wall time | Seconds from the first reservation to the last charge |
| Outcome labels | Per task: `first_pass_ok`, `ok_after_retry`, `ok_after_escalation`, `failed` |

The thesis to test is that the hierarchy (a) reaches the accuracy of the single large model (b) at a lower cost. The pitch does not depend on that thesis. If (a) costs as much as (b), or (c) is as accurate as (a), Rookwise reports it: a budget the agent cannot pass, claims checked by code, an independent audit and a human gate are worth having whichever configuration wins, and the benchmark tells the team which configuration to run.

### The incident corpus

Six fictional incidents, generated with a fixed seed by `scripts/gen_incidents.py` into `benchmarks/incidents/<id>/`. Every file says SYNTHETIC; hosts use reserved example domains and addresses come from RFC 5737. Each incident has logs from 2 or 3 services (plain text and JSON lines, 6,257 to 9,226 lines), `metrics.csv` (one row a minute over six hours), `deploy.diff`, `runbook.md`, `ticket.md` (the alert that starts the investigation) and `ground_truth.json`: the root cause and its category, essential and supporting evidence refs (source, 1-based lines, exact quote), acceptable remediations, at least 2 decoys (alarming errors unrelated to the cause), the split, the difficulty and `keyword_free_evidence` (true when no essential evidence line contains ERROR, WARN or FATAL). The ids are neutral, so an id says nothing about the cause.

| Id | Category | Split | Difficulty | Keyword-free evidence | Cause in the deploy diff | Misleading first hypothesis |
|---|---|---|---|---|---|---|
| inc-01 | certificate_expiry | dev | easy | no | no | none |
| inc-02 | resource_leak | test | easy | no | yes | none |
| inc-03 | bad_config | dev | medium | yes | yes | none |
| inc-04 | dependency_latency | test | hard | yes | no | the app deploy 25 minutes earlier |
| inc-05 | capacity_exhaustion | dev | hard | no | no | the database |
| inc-06 | disk_exhaustion | test | medium | yes | yes | none |

The category enum has 8 values (the 6 above plus `code_regression` and `network_failure`), so the enum is not just the list of answers. The logs (about 6.5 MB) are gitignored and rebuilt by the generator; the small files and `manifest.json` (the sha256 of every file) are committed, and `python scripts/gen_incidents.py --check` compares a fresh build with them.

### Cost estimate for the 36 runs (arithmetic on the corpus size, not measured)

At the harness's calibrated ratio (characters / 2.7 per file, rounded up, without the reservation's 10 percent headroom; config/harness.json `input_estimate`), the six incidents' sources (everything but the ground truth) hold 2,447,407 tokens, 327,001 to 475,641 per incident (407,901 on average). At the earlier ratio of characters / 3 they held 2,202,652. Reading every source once, input tokens only, costs per configuration over its 12 runs (2 repeats of the 6 incidents):

| Configuration | Model that reads the sources | Arithmetic | USD |
|---|---|---|---|
| (a) hierarchy | Lightning operators | 2 x 2,447,407 x 0.06 / 1M | 0.2937 |
| (b) single large model | Ultra | 2 x 2,447,407 x 1.00 / 1M | 4.8948 |
| (c) single small model | Lightning | 2 x 2,447,407 x 0.06 / 1M | 0.2937 |

These are lower bounds: they leave out output tokens, system prompts and skills, the director, managers and auditor of (a), retries, repairs and any second read. So the 36 runs cost at least USD 5.48. Reading an average incident once on Ultra also takes at least 407,901 / 200,000 = 2.0 minutes at its token limit. The context windows are UNVERIFIED, and 407,901 tokens are likely more than one prompt holds, so every configuration reads the sources in slices.

## Proof domains

Two other domains run on the same engine by swapping skills and evidence bundles. They are generality proofs shown in the README and the video, with no dedicated UI. They are not products.

| Domain | Dataset | What the evidence bundle would hold |
|---|---|---|
| SOC alert triage | splunk/attack_data | The raw logs of a few attack techniques, with the technique as ground truth |
| Smart-contract security review | ASSERT-KTH/smartbugs-curated | A few contracts with their comments stripped, with the DASP category and the vulnerable lines as ground truth |

Facts below were verified on 2026-10-17 from the repository pages only (README level). Nothing has been downloaded.

- splunk/attack_data: Apache-2.0 (README: "Copyright 2023 Splunk Inc."). The raw logs come from SIMULATED attacks, not real incidents. Datasets are organized by MITRE ATT&CK technique id under `datasets/attack_techniques/<id>/<tool>/`, with a YAML file per dataset. The whole repository is over 9 GB with Git LFS, so we fetch only a few techniques.
- ASSERT-KTH/smartbugs-curated: contracts organized by DASP category (Reentrancy, Access Control, Arithmetic, Unchecked Low Level Calls, Denial Of Service, Bad Randomness, Front Running, Time Manipulation, Short Addresses). The labels are comments in the code (a `@vulnerable_at_lines` header and `// <yes> <report> CATEGORY` lines), so the comments MUST be stripped before a model sees the code; otherwise the benchmark leaks its answers. The contracts keep their original licenses. The number of contracts is NOT verified.
- OTRF Security-Datasets (Mordor) is not used: its README contradicts itself on the license.
- Whether these public datasets appear in the models' training data is unknown. A good score on them may come from memory, not from reasoning.

## Scope cuts

- No VP and no board meeting. The contract still carries a `board` flag (always false) and a `vp` level and sender, unused.
- No reputation formula. `reputation` in a catalog entry is a static tie-breaker.
- No agent-marketplace framing: the catalog is configuration. The contract's `agent_hired` event keeps its name for compatibility; it means an agent joined the run.
- No execution of remediations in v1, and no credentials for the user's systems.
- Conventional legal-contract review is out of scope.
- No dedicated UI for the proof domains.
- Kosmo (an in-house small model in development) is not part of this submission.

## Interface and deployment

The web app (`web/`, built with Claude Code, not started) shows the chat with the director, a live feed of the run (agents, tasks, attempts, budget events), the org chart, the budget panel (predicted versus real, sub-budgets), the evidence view (each claim with its citation status, unsupported claims marked) and the approval gate. The API between `core/` and `web/` is [docs/api.md](api.md), with JSON Schemas in `docs/api/schemas/` (what the frontend consumes), synthetic fixtures in `examples/api/` and a mock server described in [docs/api-mock.md](api-mock.md).

Deployment (decided 2026-10-16, see [docs/DECISIONS.md](DECISIONS.md)):

- The web app runs on Vercel. The run executor and the live event stream run on a separate host, chosen after measuring how long a real run takes (not measured yet). VERIFIED from the Vercel docs: with Fluid compute a Vercel Function stops at 300 s on Hobby and at 800 s on Pro, streamed responses included (details in docs/api.md, "Hosting"). The API stays host-agnostic, with `Last-Event-ID` resume for reconnects.
- Recorded mode replays the stored event log of an earlier run, with its original event ids and delays, at no cost. Recorded runs are labelled as recorded in every API payload and on screen. Which real run becomes the recorded demo is chosen after the benchmark.
- Live mode makes real calls under three limits from `.env.example`: USD per run (`LIVE_DEMO_MAX_USD_PER_RUN`), USD per day for the whole deployment (`LIVE_DEMO_MAX_USD_PER_DAY`), and one live run per visitor per day (`LIVE_DEMO_MAX_RUNS_PER_VISITOR_PER_DAY`). A visitor is a signed, anonymous, HttpOnly cookie. A visitor can clear cookies, so the two USD caps are the limit that cannot be bypassed.
- A refused live request stays refused (HTTP 429 for the daily cap and the visitor limit). The UI offers a recorded run as an explicit choice; the server never falls back on its own.
- Keys in environment variables only.

## Hackathon requirements

Source: Devpost rules page, read on 2026-10-13 (summarized extract; re-read the original before submitting).
**Verify against the Devpost page before submitting:** https://nebiusglobalaihackathon.devpost.com/rules

| Requirement | How Rookwise meets it | Status |
|---|---|---|
| Nebius: a runtime call to the Token Factory inference API (or running on Nebius AI Cloud compute) | Every model call goes to Token Factory through the harness | In progress: runtime calls verified in probes (2026-10-13 to 16) and in one live smoke run of the team (2026-10-17, USD 0.010667, 14 calls) |
| At least one NVIDIA open source model | NVIDIA Nemotron at every level | In progress |
| A working demo, free and accessible for testing until the Judging Period ends (Dec 15, 2026) | `web/` on Vercel, the executor on a separate host; recorded mode costs nothing, so the demo keeps working without credits. Check credit expiry and any free-tier pausing before depending on them | Planned |
| Video: under three minutes, public on YouTube, shows the project working, no unlicensed third-party trademarks or music | Target length 2:45 | Planned |
| Public repo with source code, assets and setup instructions | Public GitHub repo; setup instructions in the README | In progress: source public; README planned |
| Open source license visible in the repository's About section | MIT `LICENSE`; GitHub detects it as MIT (checked 2026-10-13) | Done |
| README with setup instructions that highlights how Nemotron and Token Factory were used | README written last | Planned |
| Feedback on Nebius and NVIDIA tools | `FEEDBACK.md`, kept from day one | In progress |
| Track selection and a text description | Track not decided (Best Apps and Agents, or Coding and Agentic Engineering) | Open |
| Newly created after Aug 26, 2026 | Repo created 2026-10-12 | Done |
| English | All code, docs and UI text in English | In progress |
| Optional: Best Use of Tavily bonus (USD 3,000), a functional runtime call to the Tavily API as part of the solution | Operators search error signatures and advisories at runtime | Tool built; not used in a product run yet |
| Judging stage one, pass/fail: fit with the theme and reasonable use of the required APIs | Token Factory and Nemotron at every level, Tavily at runtime | Planned |
| Judging stage two: Technological Implementation, Design, Potential Impact, Quality of the Idea | Implementation: ledger, harness, evidence check, measured benchmark. Design: evidence view, budget panel, approval gate. Impact: incident investigation for teams without an SRE. Idea: trust and cost made checkable | Planned |
| Key dates: submission closes Oct 30, 2026, 10:00 am PT; judging Dec 1 to Dec 15, 2026 | Submit on the night of Oct 29; keep the demo up through Dec 15 | Planned |

## Built so far

Everything here runs offline in the tests (stubs and cassettes). Three live runs against the real models have happened, all smoke runs of the team on the synthetic `examples/team_smoke/` scenario and approved by the user (D4): USD 0.010667 (2026-10-17), USD 0.015591 and USD 0.008736 (both 2026-10-18, capped at USD 0.05; the last one recorded to a cassette). The first one cost USD 0.010667 over 14 calls and showed:

- 6 calls finished with `finish_reason: "length"`;
- 6 charges exceeded their reservation by 3 to 5 percent;
- the input estimate of characters / 3 undercounted the prompts with logs by about 10 percent (3,841 estimated, 4,248 real);
- the ledger prediction was 0, because nothing set it;
- operators passed on the first try 0 of 5 times;
- `citation_verified_rate` was 0.591 (13 of 22), because multi-line quotes failed the quote check (a format problem, not fabrication).

Changed after it (2026-10-18; tested on stubs, not yet in a live run): every role has an explicit output ceiling that the ledger reserves, and a `length` finish is a typed outcome that is not retried; a task that hits its own ceiling gets one reassignment, while a ledger stop ends its scope; citations are single-line and checked in the output schema; the input estimate uses a calibrated 2.7 characters per token plus 10 percent headroom; every call records a predicted cost next to its real cost. See docs/DECISIONS.md, "After the first live run".


- Harness (`core/harness/`, Stages 1 and 2, 2026-10-15 and 16): streaming calls with usage, the reserve, charge and release cycle with the ledger, per-model request and token limits and a concurrency cap, bounded retries with `Retry-After`, cancellation, record and replay of model calls and tool results (`HARNESS_MODE`), native tool calls, the tool loop with `json_protocol` and `native_tools`, step, repeat, timeout, truncation and token limits, `finish_reason: "length"` discarded and ended as a typed outcome at the role's output ceiling, final-answer validation with up to two repairs, then the escalation ladder, one `AttemptRecord` per attempt and the outcome labels. `on_missing_usage` charges the full reservation and marks the usage estimated.
- Ledger and money (`core/ledger.py`, `core/money.py`): `Decimal` end to end, whole micro-USD with the rounding rules in "Cost of a call", caps per run, level and task, and allocations (`allocate`, `close`, `free`; a call reserved with a `budget_id` is drawn from that allocation). A float passed to the ledger raises TypeError.
- Runner (`core/runner.py`): `run_operator`, one task_v1 for one catalog operator, inside an optional allocation.
- Evidence check (`core/evidence.py`): the rule in "The evidence rule", with a reason code per citation and per claim, the verified rate and the unsupported claims.
- Team skeleton (`core/team/`): director, managers, operators and auditor on the harness and the runner only, run one after another; the plan call, the auditor's and the managers' allocations, one allocation per operator assignment, reassignment to the next catalog operator and escalation to the director, one consolidation call per manager, the auditor with the evidence check first. A level that runs out of budget ends cleanly with a `budget_exhausted` event. Every step emits API contract events, including `budget_allocation`, `budget_exhausted` and `escalation`.
- API contract v1 (`core/api/models.py`, docs/api.md): generated JSON Schemas, synthetic fixtures, a standard-library mock server, money as six-decimal strings.
- Skills (`skills/`, `core/skills/`): nine adapted skills with attribution and measured token costs, and three original incident reading skills for the roles `log-reader`, `metrics-reader` and `deploy-diff-reader` (2026-10-19; not measured yet, so their token counts are the loader's labeled estimate).
- Tavily search tool (`core/tools/tavily.py`), verified with one live query (2026-10-16).
- Incident corpus (`scripts/gen_incidents.py`, `benchmarks/incidents/`, 2026-10-17): the six incidents in "The incident corpus", with their ground truth and the manifest.
- Corpus access and scorer (`core/incidents.py`, 2026-10-17): `load_bundle(incident_id)` returns an incident's sources as an `EvidenceBundle` (source ids are the file paths inside the incident, lines are 1-based, every file is checked against the manifest's sha256, the ground truth is left out); `load_ground_truth`; and `score(claims, truth, category=...)`, the deterministic scorer of `diagnosis_correct`, `citation_verified_rate` and `evidence_recall` from "Benchmark design", with no model.
- Smoke run (`scripts/team_smoke.py`, `examples/team_smoke/`, 2026-10-17): a SYNTHETIC scenario (a 60-line app log and a runbook with a planted root cause) and a script with four modes: `estimate` (offline, on a stub transport), `record` and `live` (one live run under a run cap, `--run-usd`), and `replay` (from the recorded cassette, no network). Its run summary gives real and predicted cost per role and per model, the outcome of each agent call by role, and the number of `length` finishes.
- Slicer (`core/slicing.py`, `config/slicing.json`, 2026-10-19): splits a source at line boundaries into ordered slices with absolute line numbers, rendered as agents read sources (`<number>: <line>`), sized by the calibrated input estimate, with `overlap_lines` shared between consecutive slices; a line larger than the budget becomes its own oversized slice (never dropped or truncated), an empty source has no slices and is listed, and `coverage` returns any line range no slice covers. `max_slice_tokens` 12000 and `overlap_lines` 10 are placeholders, UNVERIFIED against the context window. It imports nothing from `core/team`, so the baselines can reuse it.
- Slice assignment (`core/team/flow.py`, 2026-10-19): each plan task names a role and the source it reads, and the director's run-bound output model (`plan_model`) fails validation, repairably, unless every non-empty source is read, so the plan covers every slice. Each slice of a task's source is its own operator task; the slice is stored at `store://<run>/slices/<source>:<first>-<last>` and is the task's only `inputs` entry (task_v1 is unchanged), so the operator reads only that slice. Citations are still validated against the full sources. `TeamRun.unread_slices` lists the line ranges no completed operator task read, and the director's closing message names them; `TeamRun.empty_sources` lists empty sources.
- Diagnosis scoring (`core/benchmark.py`, 2026-10-19): `score_diagnosis` withdraws the diagnosis's unsupported claims (D3) and calls `core/incidents.py` `score` with the category and the supported claims only; it also returns the citation first-pass validity, the repairs spent on citation errors and the number of withdrawn claims. Attempt records keep only error text, so each run-bound output model records every citation of every validated reply (`CitationLog`, `TeamRun.citation_log`, and `citation_checks` in the smoke report). `score_run` reads it all from a `TeamRun`.
- Withdrawal of unsupported claims (D3, `core/team/auditor.py`, 2026-10-19): the rule in "The evidence rule", with the `audited` and `inconclusive` statuses and the counts per reason code.
- Director's diagnosis (`core/team/models.py` `Diagnosis`, `core/team/flow.py`, 2026-10-19): after the managers, the director makes one more call and returns the root cause, its category (the benchmark's enum from `core/incidents.py`), claims with citations (validated for shape only; a wrong quote is withdrawn under D3, with one targeted repair when every root-cause claim is withdrawn), the ids of the claims the root cause rests on, and a remediation plan of steps with action, why, risk and reversible. v1 executes nothing. The director receives the context sources in full (`context_sources`, for example the ticket and the runbook), the source inventory, and the managers' summaries and operators' findings under their store references, and may cite evidence lines directly.
- Stage-0 log filter experiment (`benchmarks/log_filter/`, 2026-10-17): a closed experiment. It ran a keyword filter and Laya on a separate synthetic corpus, and Laya was rejected (report in `benchmarks/log_filter/REPORT.md`). The folder stays only as the record of that experiment; the benchmark uses `benchmarks/incidents/` only.

Not built yet: the approval of the remediation plan, the single-model baselines (b) and (c), the benchmark runner, the auditor's correction cycle, parallel managers and operators, per-call `tool_called` events, cancellation of a team run, reading `x-ratelimit-*` headers, the server and `web/`.

## Risks and not verified

- Three live runs only, all on the synthetic 60-line smoke log, none on an incident of the corpus. `BudgetPolicy` is still a set of placeholders.
- Context windows are UNVERIFIED. An incident's logs are far larger than one prompt, so every configuration reads them in slices (D1); the slice size is a placeholder until it is checked against the context window.
- The `diagnosis_correct` rule is a proposal: a category match plus one verified essential citation. A model can name the right category for the wrong reason; evidence recall and the auditor partly cover that.
- The corpus is synthetic. Real incidents are messier; good scores on it do not prove field accuracy, and the keyword-free incidents are our guess at what makes an incident hard.
- Public datasets in the proof domains may be in the models' training data (unknown).
- Reasoning-token billing, cached-token billing and Tavily's per-query cost are UNVERIFIED.
- Listed model speeds are not reproduced, and the duration of a real run is NOT MEASURED, so the executor host is open.
- Credits: USD 26 in total (25 event credit plus 1 account credit; unverified, check the Nebius console), minus what the probes spent (each probe's spend is in `docs/HARNESS_RESEARCH.md`) and the three smoke runs' USD 0.034994 (0.010667, 0.015591 and 0.008736). The benchmark costs at least USD 5.48 (see "Cost estimate for the 36 runs"); the real figure is unknown until the first measured runs.
- The auditor is a model and may favor outputs like its own. Mitigation: the deterministic check first, a fixed rubric, a separate context, human review of a sample.

## Timeline, October 17 to 29 (a plan, not a commitment)

About 3 hours a day. Submission on the night of October 29 for the October 30, 10:00 AM PDT deadline.

| Date | Work |
|---|---|
| Oct 17 | Product definition, this document, the incident corpus and the deterministic scorer |
| Oct 18 | Incident roles and skills; slicing the evidence across operators; the director's diagnosis (category, cited claims, remediation plan) |
| Oct 19 | First live run on one dev incident (only after the user approves it with a cost estimate); cassettes; Tavily on error signatures |
| Oct 20 | Single-model baselines (b) and (c); measure a real run's duration and choose the executor host |
| Oct 21 | Tune on the dev incidents only, then freeze prompts, skills and `BudgetPolicy` |
| Oct 22 | The 36 benchmark runs; report test separately from dev |
| Oct 23 to 24 | `web/`: chat, live feed, org chart, budget panel, evidence view, approval gate, recorded mode |
| Oct 25 | Deploy the web app and the executor with the live caps |
| Oct 26 | Proof domains: one run each on a few splunk/attack_data techniques and a few smartbugs-curated contracts with comments stripped |
| Oct 27 | Choose the recorded demo; fixes; `FEEDBACK.md` |
| Oct 28 | README; video script and recording |
| Oct 29 | Video edit, Devpost text, submission |

## Development toolchain (Claude Code plugins)

Rookwise is built with Claude Code and a small set of plugins and skills: stop-slop for human-facing text, ponytail as a guard against over-building in `core/`, harness-engineering as a Claude Code workflow that plans the work, builds it in stages and checks the result, and the engineering and incident.io plugins from the user's account. They run at development time only. The Rookwise runtime (`core/`, Nemotron on Nebius Token Factory) must not depend on any of them, and their cost comes from the Claude plan, not from the Nebius credits. The runtime uses adapted, attributed copies of four of them in `skills/` (see "Skills layer"). harness-engineering is a development workflow and is not the Rookwise harness in `core/harness/`. Setup, pinned versions, licenses, per-tool rules and the boundary are in [docs/PLUGINS.md](PLUGINS.md).

## Open decisions

Listed with their context in [docs/DECISIONS.md](DECISIONS.md), "Still open": the Devpost track; which real run becomes the recorded demo; the executor host; whether to commit recordings; the reasoning-token billing check in the Nebius console; Nano's tool protocol; the model ladder. Also open in this document: the incident roles; the store (Supabase or SQLite).
