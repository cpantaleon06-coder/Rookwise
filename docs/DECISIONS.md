# Decisions log

Decisions made by the user, with their date and the reason recorded at the time. Where a decision changed a document or the contract, the place is named. Open items are at the end.

## API contract and deployment (2026-10-16)

| # | Decision | Reason | Where |
|---|---|---|---|
| 1 | A visitor is a signed, anonymous, HttpOnly cookie. Limit: 1 live run per visitor per day (`LIVE_DEMO_MAX_RUNS_PER_VISITOR_PER_DAY=1`). The global daily USD cap and the per-run USD cap stay as the real backstop. | Spreads the live budget over visitors without accounts or personal data. A visitor can clear cookies and start again, so only the USD caps, which the ledger enforces on every call, cannot be bypassed. | docs/api.md "Visitors"; `.env.example`; `LiveCaps` in `core/api/models.py` |
| 2 | Recorded mode replays stored event logs (original event ids and delays), not harness cassettes. Recorded runs are labelled as recorded in every API payload and in the docs. Which real run becomes the recorded demo is still open. | An event log replays exactly what the UI saw, costs nothing and needs no model or tool code at serve time. Labelling stops a recording from passing for a live run. | docs/api.md "Modes"; `mode` on every event and run-scoped view |
| 3 | A refused live request stays HTTP 429 with its refusal reason. There is no automatic fallback; the client offers a recorded run as an explicit user action. | The user must know they are not watching a live run; a silent switch would hide that. | docs/api.md "Modes"; mock server |
| 4 | Hosting: the web app on Vercel; the run executor and the live event stream on a separate host, chosen after measuring the duration of a real run. The contract stays host-agnostic, with `Last-Event-ID` resume. | VERIFIED (https://vercel.com/docs/functions/limitations, read 2026-10-16): with Fluid compute a Vercel Function runs at most 300 s on Hobby (default and maximum) and 800 s on Pro, streamed responses included (Pro and Enterprise also list an 1800 s extended maximum in beta). The length of a real run is NOT MEASURED, so a run may not fit. | docs/api.md "Hosting"; docs/ARCHITECTURE.md "Interface and deployment" |
| 5 | `run_id` is an opaque string with a prefix (`run_` plus a random identifier); the UI must not parse ids. Money: the API sends exact values and the UI formats them. | Opaque ids leave the server free to change their format. Sending exact values keeps the ledger as the only place money is computed. The ledger uses Python floats today, so sums carry floating-point noise (the fixture total is `0.013171559999999999`); `Decimal` or integer micro-USD is a proposed follow-up, and the ledger is not changed now. | docs/api.md "Conventions"; fixtures |
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

## Still open

- **Executor host**: which host runs the run executor and the live event stream. Chosen after measuring how long a real run takes.
- **Recorded demo**: which real run becomes the recorded demo. Chosen after the benchmark.
- **Demo recordings in git**: whether demo recordings (event logs) are committed to the repository.
- **Reasoning-token billing**: whether Token Factory bills reasoning tokens at the output price. `completion_tokens` includes them (VERIFIED); check the billed amount against the Nebius console.
- **Nano's tool protocol**: revisit after the benchmark.
- **Model ladder**: escalation inside the runner, with a manager reassigning only after the ladder is exhausted, is proposed and pending the user's decision (docs/ARCHITECTURE.md "Failures and loops").
- **Domain and demo cases**: the ITOps and DevOps domain, and the final demo cases.
- **Ledger money type**: whether to move from floats to `Decimal` or integer micro-USD (proposed follow-up).
