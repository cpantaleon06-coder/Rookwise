# Decisions log

Decisions made by the user, with their date and the reason recorded at the time. Where a decision changed a document or the contract, the place is named. Open items are at the end.

## API contract and deployment (2026-10-16)

| # | Decision | Reason | Where |
|---|---|---|---|
| 1 | A visitor is a signed, anonymous, HttpOnly cookie. Limit: 1 live run per visitor per day (`LIVE_DEMO_MAX_RUNS_PER_VISITOR_PER_DAY=1`). The global daily USD cap and the per-run USD cap stay as the real backstop. | Spreads the live budget over visitors without accounts or personal data. A visitor can clear cookies and start again, so only the USD caps, which the ledger enforces on every call, cannot be bypassed. | docs/api.md "Visitors"; `.env.example`; `LiveCaps` in `core/api/models.py` |
| 2 | Recorded mode replays stored event logs (original event ids and delays), not harness cassettes. Recorded runs are labelled as recorded in every API payload and in the docs. Which real run becomes the recorded demo is still open. | An event log replays exactly what the UI saw, costs nothing and needs no model or tool code at serve time. Labelling stops a recording from passing for a live run. | docs/api.md "Modes"; `mode` on every event and run-scoped view |
| 3 | A refused live request stays HTTP 429 with its refusal reason. There is no automatic fallback; the client offers a recorded run as an explicit user action. | The user must know they are not watching a live run; a silent switch would hide that. | docs/api.md "Modes"; mock server |
| 4 | Hosting: the web app on Vercel; the run executor and the live event stream on a separate host, chosen after measuring the duration of a real run. The contract stays host-agnostic, with `Last-Event-ID` resume. | VERIFIED (https://vercel.com/docs/functions/limitations, read 2026-10-16): with Fluid compute a Vercel Function runs at most 300 s on Hobby (default and maximum) and 800 s on Pro, streamed responses included (Pro and Enterprise also list an 1800 s extended maximum in beta). The length of a real run is NOT MEASURED, so a run may not fit. | docs/api.md "Hosting"; docs/ARCHITECTURE.md "Interface and deployment" |
| 5 | `run_id` is an opaque string with a prefix (`run_` plus a random identifier); the UI must not parse ids. Money: the API sends exact values and the UI formats them. | Opaque ids leave the server free to change their format. Sending exact values keeps the ledger as the only place money is computed. At the time the ledger used Python floats, so sums carried floating-point noise (the fixture total was `0.013171559999999999`). Superseded on 2026-10-17 by "Money" below. | docs/api.md "Conventions"; fixtures |
| 6 | The contract models stay in `core/api/models.py`; the generated JSON Schemas in `docs/api/schemas/` are what the frontend consumes. | One source for the schemas, reusable by the Stage 3 server; the frontend needs no Python. | docs/api.md introduction |
| 7 | The UI shows cancel only; no pause or resume controls until core supports them. | Core can cancel a run (asyncio or `CancelHandle`) but cannot pause one. The API reserves pause and resume (HTTP 501). | docs/api.md "Endpoints"; docs/ARCHITECTURE.md "Administrator layer"; mock server |
| 8 | `web/` is built with Claude Code; GLM is not available. | GLM is not available to the project. | docs/ARCHITECTURE.md "Rules", "Interface and deployment"; docs/PLUGINS.md |

## Harness, Stage 2 (2026-10-16)

| Decision | Where |
|---|---|
| `on_missing_usage` stays `charge_full_reservation`. | config/harness.json |
| `LedgerEntry` carries `usage_estimated` (default false). | core/schemas.py; docs/ARCHITECTURE.md "Messages and shared store" |
| `finish_reason: "length"` is never a success: the content is discarded, one retry with a larger `max_tokens`, then a failure for escalation. Superseded on 2026-10-18: no retry, see "After the first live run". | core/harness/loop.py |
| `temperature` and `top_p` stay at server defaults, overridable per call and per operator only. | config/harness.json; `OperatorSpec` |
| Nano stays on `json_protocol`, to revisit after the benchmark. In the reliability run (docs/HARNESS_RESEARCH.md, "Tool-calling reliability") Nano with `native_tools` succeeded 15 of 15 and with `json_protocol` 14 of 15, while the earlier single-sample probe had shown problems. | config/harness.json |

## Money (2026-10-17)

| Decision | Reason | Where |
|---|---|---|
| All money in core is `decimal.Decimal`, never float: prices (parsed from the JSON text), reservations, charges, caps, predictions and run totals. A float passed to the ledger raises TypeError. | Exact sums; no floating-point noise in totals or cap checks. | `core/money.py`, `core/ledger.py`, `core/schemas.py`, `core/harness/`, `core/runner.py` |
| The ledger holds whole micro-USD and rounding must never let spend pass a cap. | Exact totals at the precision the API shows. | `core/ledger.py` |
| In the API contract every money field is a decimal string with exactly six decimals (`"0.002350"`), requests included; a JSON number is refused (422). Part of v1. | Strings carry the exact value to the browser; the web app did not consume the contract yet. | `core/api/models.py`, docs/api.md "Conventions", `docs/api/schemas/`, `examples/api/` |
| Implementation choices, pending the user's review: reservations and charges round up (ROUND_CEILING), caps round down (ROUND_FLOOR), predictions round half-even; models refuse amounts finer than a micro-USD instead of rounding them; `CostReport.prediction_error` is a ratio and stays a JSON number. | Rounding up costs and down caps is what keeps both recorded and real spend under a cap; predictions gate nothing. | `core/ledger.py` docstring; `core/money.py`; docs/ARCHITECTURE.md "Cost of a call" |

## Team hierarchy skeleton (2026-10-17)

| Decision | Reason | Where |
|---|---|---|
| Sub-budgets are ledger allocations: `allocate` holds an amount out of the run or out of a parent allocation, a call reserved with that `budget_id` is drawn from it, `close` gives the unspent part back. The ledger enforces that children never hold more than their parent. | The ledger only reserved one model call at a time and had flat caps; the hierarchy needs sub-budgets the ledger itself enforces. | `core/ledger.py`; docs/ARCHITECTURE.md "Administrator layer" |
| The team emits only the contract's existing event types; missing events are proposed, not added. Superseded later on 2026-10-17 by "Hierarchy events" below. | Keep the contract unchanged until the additions are reviewed. | `core/team/events.py`, `core/team/flow.py` |
| Implementation choices, pending the user's review: `BudgetPolicy` defaults (auditor 25% of what is free after the plan, equal split per block, a manager keeps 30% for its own call, one reassignment; placeholders, not measured); a reassigned task gets a new task_v1 id (`t-1.2`) so its ledger task cap and token budget start fresh; an operator that stopped on its budget is not reassigned; the auditor rejects without a model call when the deterministic check fails, and accepts with a warning when its model review could not run; `run_failed` uses the codes `budget_exhausted`, `plan_failed` and `plan_too_large`; managers run one after another. | A skeleton that the benchmark can tune. | `core/team/config.py`, `core/team/flow.py`, `core/team/auditor.py` |

## Hierarchy events (2026-10-17)

| Decision | Reason | Where |
|---|---|---|
| Added to the v1 contract: `budget_allocation` (`action`: allocated or released, `agent_id`, `parent_agent_id`, `usd`, `parent_free_usd`), `budget_exhausted` (`agent_id`, `level` and the `CapStop` fields) and `escalation` (`from_agent_id`, `to_agent_id`, `task_id`, `reason`); and `"budget"` in `CapStop.scope`, the scope of a stopped allocation. The team emits them: `budget_allocation` on every ledger `allocate` and `close`, `budget_exhausted` wherever a level stops on its budget, and `escalation` on a reassignment and on an escalation to the director. | Before, a manager that ran out of budget showed only as a director `message` and `run_finished` with `partial: true`, and the UI had no way to show sub-budgets or reassignments. | `core/api/models.py`, `docs/api/schemas/`, docs/api.md "Event catalog", `core/team/flow.py`, `examples/api/` |
| Implementation choices, pending the user's review: `parent_agent_id` is the director for allocations drawn from the run (the director holds the run budget; this includes the auditor's); on a reassignment `to_agent_id` is the next operator, hired just before the event, so the UI links the failed task to the new one without parsing ids; `escalation.task_id` is null when a manager escalates a whole block with no completed task, and the manager's own call (`b-1-summary`) when it could not consolidate; `budget_exhausted` is sent only for a ledger stop (`CapReached`), not for a token ceiling or a manager with nothing left for an operator; the auditor and every manager are now hired right after the plan, before their allocations (the hire order changed); the synthetic fixture run gained a third task that is reassigned and then stops on its budget, so it is now partial and its total is `"0.015903"`. | Every event names only agents already hired (docs/api.md, "Ordering and idempotency"), and every `CapStop` field is the ledger's own value. | `core/team/flow.py`, `scripts/gen_api_fixtures.py`, docs/api.md |

## Product definition (decided by the user, 2026-10-17)

| Decision | Where |
|---|---|
| Primary product: operational incident investigation (ITOps and DevOps) for small teams without a dedicated SRE, under a hard budget the user sets. Cheap models read the volume of logs and metrics, a strong model judges, deterministic code (not a model) verifies that every claim cites real evidence, an independent auditor checks the result, and a human approves before anything is done. Every run reports predicted versus real cost, and accuracy is measured against known root causes. The engine stays domain-neutral: roles, skills and evidence bundles are data. | docs/ARCHITECTURE.md, all sections |
| Conventional legal-contract review is out of scope. | docs/ARCHITECTURE.md "Scope cuts" |
| Two proof domains run on the same engine by swapping skills and evidence bundles: SOC alert triage and smart-contract security review. They are generality proofs shown in the README and the video, with no dedicated UI. They are not products. | docs/ARCHITECTURE.md "Proof domains" |

## After the first live run (decided by the user, 2026-10-18)

The first live smoke run (USD 0.010667, 14 calls) showed six `length` finishes, charges above their reservation, a ledger prediction of 0 and multi-line quotes failing the evidence check. The user decided these changes.

| Decision | Where |
|---|---|
| Every role has an explicit output ceiling, `max_output_tokens` in config/skills.json; each call of the role is sent with it and the ledger reserves it. A `length` finish is a typed outcome (`loop_status` `length`, `LengthStop` with the ceiling that cut it) that ends the attempt at once; it is never retried with the same ceiling. Values (an implementation choice, pending the user's review): 4096 for operator roles (what one length retry used to reach), 2048 for the director, manager and auditor (the model default they ran with). | config/skills.json; core/harness/loop.py; core/harness/escalate.py |
| A task ceiling (`length` or `token_ceiling`: the task hit its own output ceiling or token budget) is separate from a ledger stop (`budget_exhausted`: the ledger refused a reservation). A task ceiling gets at most one reassignment, to the next catalog operator for the role or, with none left, to the same operator one rung up `escalation.next`. A ledger stop ends its scope, is not reassigned and emits `budget_exhausted` as in contract v1. Only operators are reassigned; a director, manager or auditor call that hits its ceiling fails as before. | core/team/flow.py |
| Citations are single-line: an agent's citation has exactly `source_id`, `line_start`, `line_end` and `quote`, and a quote with a line break fails the output schema, so it is repaired (and counts toward the repair limit) before the evidence check. The operator and auditor prompts say so. `core/evidence.py` is unchanged. | core/team/models.py; core/team/flow.py; core/team/auditor.py |
| The input estimate uses a calibrated 2.7 characters per token (from the first live run) plus a headroom, both in config/harness.json `input_estimate`. Headroom 0.10 is an implementation choice, pending the user's review: with it every one of the 14 recorded calls is covered, without it 5 are under. The test runs on 4 of those calls, committed as `tests/fixtures/cassettes/team_smoke_inputs.json` (inputs and reported prompt_tokens only), because the committed cassettes come from the mock transport and carry made-up counts (the user chose this on 2026-10-18). | config/harness.json; core/harness/request.py; tests/test_input_estimate.py |
| The ledger prediction is wired: every call records a predicted cost next to its real cost, summed per run and per model in `RunReport` and in the smoke run summary. When the caller passes no `usd_predicted`, the harness predicts the input estimate without headroom plus `prediction.output_fraction` of `max_tokens`; 0.5 is an implementation choice, pending the user's review, not a measurement. `scripts/team_smoke.py` also gained a `live` mode and `--run-usd` for the capped second run. | core/ledger.py; core/harness/request.py; core/harness/client.py; config/harness.json; scripts/team_smoke.py |
| Laya is rejected. `benchmarks/log_filter/` is a closed experiment, kept only as its record (`benchmarks/log_filter/REPORT.md`); the benchmark uses `benchmarks/incidents/` only. | docs/ARCHITECTURE.md "Built so far" |
| Each quote must sit inside a single source line of its cited range (whitespace-normalized substring of one line), checked at validation as a repairable error through a run-bound output model in core/team (`findings_model`); the harness and runner are unchanged (the user chose this over a validation context or a check hook in the harness, 2026-10-18). The operator and auditor prompts say to copy one line verbatim with its timestamp, give several citations for several lines and never join lines. | core/team/models.py; core/team/flow.py; core/team/auditor.py |

## Slicing, caps and unsupported claims (decided by the user, 2026-10-18)

| # | Decision | Where |
|---|---|---|
| D1 | The single-model baselines (b) and (c) read the evidence in slices, with the same slicer as the hierarchy (a). | docs/ARCHITECTURE.md "Benchmark design"; `core/slicing.py` |
| D2 | Caps per incident are config values per configuration: USD 0.10 for (a); (b) and (c) run with a safety cap of USD 1.00 and report their cost to reach an answer. The 0.10 is unmeasured and is revisited after the first approved run on a dev incident. | docs/ARCHITECTURE.md "Benchmark design" |
| D3 | Unsupported claims are withdrawn from the deliverable (and listed, never hidden), and the auditor model reviews the supported rest. Built on 2026-10-19: unsupported claims of the diagnosis move to `withdrawn_claims` with their reason codes; with every root-cause claim withdrawn or no supported claim left, the diagnosis is `inconclusive` and the auditor makes no model call; otherwise it is `audited` and the auditor gets the supported claims, the withdrawn list and its rubric. On 2026-10-19 the user decided that the director's diagnosis is validated for shape only, so its bad citations are withdrawn instead of rejecting the whole reply, with exactly one targeted repair request when every root-cause claim is withdrawn (then inconclusive if it still fails); operators keep the strict run-bound validation. Kept as shape: a quote with a line break still fails validation (implementation choice, pending the user's review). Implementation choices, pending the user's review: an inconclusive result is emitted as `audit_result` verdict `rejected` with a failed check and a warning (contract v1 has no inconclusive verdict); an accepted diagnosis with withdrawn claims becomes `accepted_with_warning`; the auditor reads only the cited lines with two lines of context. | docs/ARCHITECTURE.md "The evidence rule"; core/team/auditor.py |
| D4 | The user approved the earlier live and record runs (2026-10-17 and 2026-10-18). | docs/ARCHITECTURE.md "Built so far" |

## Pooled operator budgets (decided by the user, 2026-10-19)

| Decision | Where |
|---|---|
| The operators of a block reserve from one pool (a ledger allocation) instead of an even per-task slice; the ledger refuses what the pool or the run cannot cover, and money is held only while a call is in flight. A runaway task stops at a per-task limit counted as money spent (the ledger's task cap), default 4 times its first reservation. Blocks get money in proportion to their estimated work; the director's, the auditor's and the manager's shares are explicit in config. Implementation choices, pending the user's review: `director_share` 0.20 (new; it was implicit before), the limit's base is the first reservation of the cheapest operator for the role, so a reassignment one rung up the ladder may not fit in what is left of the limit; a reassignment gets what the task's limit has left. | core/team/flow.py; core/team/config.py; config/budget.json |
| Block pools by max-min fairness (decided by the user, 2026-10-20): smallest estimated need first, each block gets the smaller of its need and an equal share of what remains, the largest block gets the rest, and blocks are allocated just before they run so unspent money rolls forward. The need uses `expected_output_tokens_per_operator` (1000, a placeholder). Implementation choices, pending the user's review: the need includes one reservation's headroom for the call in flight; the manager keeps the larger of `manager_share` and one estimated consolidation reservation (estimated from a request of counts only, so large findings can still exceed it). | core/team/flow.py; config/budget.json |
| Ladder-aware per-task limit and a startup check (decided by the user, 2026-10-20): a task may spend 3 first-rung reservations plus 1 next-rung reservation (config values), and a run whose `max_slice_tokens` plus the operator prompt overhead estimate passes `operator_max_input_tokens` fails at start, naming both keys. Implementation choice, pending the user's review: the overhead estimate allows an instruction of up to 600 characters. | core/team/flow.py; core/team/config.py; config/budget.json |

## Still open

- **Executor host**: which host runs the run executor and the live event stream. Chosen after measuring how long a real run takes.
- **Recorded demo**: which real run becomes the recorded demo. Chosen after the benchmark.
- **Demo recordings in git**: whether demo recordings (event logs) are committed to the repository.
- **Reasoning-token billing**: whether Token Factory bills reasoning tokens at the output price. `completion_tokens` includes them (VERIFIED); check the billed amount against the Nebius console.
- **Nano's tool protocol**: revisit after the benchmark.
- **Model ladder**: escalation inside the runner, with a manager reassigning only after the ladder is exhausted, is proposed and pending the user's decision (docs/ARCHITECTURE.md "Failures and loops").
- **Devpost track**: Best Apps and Agents, or Coding and Agentic Engineering.
