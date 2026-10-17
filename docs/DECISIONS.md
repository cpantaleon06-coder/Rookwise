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
| `finish_reason: "length"` is never a success: the content is discarded, one retry with a larger `max_tokens`, then a failure for escalation. | core/harness/loop.py; config/harness.json `length_retry` |
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
| The team emits only the contract's existing event types; missing events are proposed, not added (see "Still open"). | Keep the contract unchanged until the additions are reviewed. | `core/team/events.py`, `core/team/flow.py` |
| Implementation choices, pending the user's review: `BudgetPolicy` defaults (auditor 25% of what is free after the plan, equal split per block, a manager keeps 30% for its own call, one reassignment; placeholders, not measured); a reassigned task gets a new task_v1 id (`t-1.2`) so its ledger task cap and token budget start fresh; an operator that stopped on its budget is not reassigned; the auditor rejects without a model call when the deterministic check fails, and accepts with a warning when its model review could not run; `run_failed` uses the codes `budget_exhausted`, `plan_failed` and `plan_too_large`; managers run one after another. | A skeleton that the benchmark can tune. | `core/team/config.py`, `core/team/flow.py`, `core/team/auditor.py` |

## Still open

- **Executor host**: which host runs the run executor and the live event stream. Chosen after measuring how long a real run takes.
- **Recorded demo**: which real run becomes the recorded demo. Chosen after the benchmark.
- **Demo recordings in git**: whether demo recordings (event logs) are committed to the repository.
- **Reasoning-token billing**: whether Token Factory bills reasoning tokens at the output price. `completion_tokens` includes them (VERIFIED); check the billed amount against the Nebius console.
- **Nano's tool protocol**: revisit after the benchmark.
- **Model ladder**: escalation inside the runner, with a manager reassigning only after the ladder is exhausted, is proposed and pending the user's decision (docs/ARCHITECTURE.md "Failures and loops").
- **Domain and demo cases**: the ITOps and DevOps domain, and the final demo cases.
- **Contract additions for the hierarchy (proposed, not added)**: three event types, `budget_allocation` (`action`: allocated or released, `agent_id`, `parent_agent_id`, `usd`, `parent_free_usd`), `budget_exhausted` (`agent_id`, `level` and the `CapStop` fields) and `escalation` (`from_agent_id`, `to_agent_id`, `task_id`, `reason`); and `"budget"` in `CapStop.scope`, the scope of a stopped allocation. Until then a manager that runs out of budget shows only as a director `message` and `run_finished` with `partial: true`.
