# Rookwise API v1 (core/ to web/)

Status: **draft, frontend may start.** Field names may still change before the server is built (Stage 3); any change is made here first, in the models in `core/api/models.py`, and in the generated schemas. Written on 2026-10-16.

This is the only interface between `core/` (Python, built with Claude Code) and `web/` (built with GLM). The web app never calls Token Factory, Tavily or any model API: it calls this API only.

Sources of truth, in order:

1. `core/api/models.py`: pydantic models of every payload. They reuse the models that already exist in `core/` (`TaskV1`, `ResultV1` and `LedgerEntry` from `core/schemas.py`, `AttemptRecord` and the outcome labels from `core/harness/escalate.py`, the ledger's `RunReport`, `Caps` and `CapReached` fields, and the catalog fields of `OperatorSpec` in `core/runner.py`).
2. `docs/api/schemas/*.json`: JSON Schemas generated from those models (`python scripts/gen_api_schemas.py`). A test fails when a committed schema drifts from its model.
3. `examples/api/`: synthetic fixtures (`python scripts/gen_api_fixtures.py`), validated by `tests/test_api_contract.py`. They are not real model output and say so.
4. `docs/api-mock.md` and `examples/api/mock/serve.py`: serve the fixtures and replay the event stream without the backend.

## Conventions

- Base path `/api/v1`. JSON in UTF-8 everywhere except the event stream (Server-Sent Events).
- Timestamps are ISO 8601 in UTC (`2026-10-20T15:00:00Z`).
- Money is USD as a JSON number, unrounded, as the ledger computes it (`usd_real` and friends). The UI rounds for display.
- Ids are opaque strings: `run_id` (for example `run_8f2c1a7d4b`), `task_id`, `agent_id`, `message_id`, `recording_id`. Event ids are `<run_id>:<seq>`.
- Roles, skills, tools and models are plain strings (`"researcher"`, `"prose-style"`, `"tavily_search"`, `"nemotron-3.5-lightning"`). The demo domain only changes data, never the API.
- Unknown fields are rejected in requests (HTTP 422) and never sent in responses; every object in the schemas has `additionalProperties: false`.

## Modes

| Mode | What it does | Cost |
|---|---|---|
| `recorded` | Replays a saved run, event by event, with its original timing | Nothing |
| `live` | Runs the agents on Token Factory under the live caps | Real credits |

`GET /api/v1/modes` (`ModesView`) says which modes are available now, and why live is not: `refusal` is one of

| `refusal` | Meaning | HTTP status on `POST /runs` |
|---|---|---|
| `live_disabled` | Live mode is off on this deployment (no key or switched off) | 503 |
| `run_cap_exceeded` | The requested `budget_usd` is above `max_usd_per_run` | 422 |
| `daily_cap_reached` | Live spend today reached `max_usd_per_day` | 429, with `Retry-After` (seconds to the daily reset) |
| `visitor_limit_reached` | This visitor used up their live runs for today | 429, with `Retry-After` |

The caps come from `LIVE_DEMO_MAX_USD_PER_RUN` and `LIVE_DEMO_MAX_USD_PER_DAY` (`.env.example`). The visitor limit has no setting yet (see "Not in core yet"). The server never switches a run from live to recorded on its own: a refused live request gets an error, and the UI may then offer a recorded run. Every run states its mode (`RunView.mode`); a recorded run also starts with a `mode_notice` event (`recorded_mode`). If the caps run out between creating a live run and starting it, the stream sends `mode_notice` (`live_refused`) and then `run_failed` with code `live_refused`, and nothing is spent. Example: `examples/api/live_refused.json`.

## Endpoints

| Method and path | Request | Response | Notes |
|---|---|---|---|
| `GET /api/v1/modes` | | 200 `ModesView` | Modes, live caps and today's live spend, available recordings |
| `POST /api/v1/runs` | `CreateRunRequest` | 201 `RunView` | Live needs `goal` and `budget_usd`; recorded needs `recording_id`. Optional `Idempotency-Key` header |
| `GET /api/v1/runs` | `?cursor=` | 200 `RunList` | Newest first, paginated with `next_cursor` |
| `GET /api/v1/runs/{run_id}` | | 200 `RunView` | Status, mode, caps, spent, held and predicted USD |
| `GET /api/v1/runs/{run_id}/events` | `Last-Event-ID` header or `?last_event_id=` | 200 `text/event-stream` | The live feed (next section) |
| `GET /api/v1/runs/{run_id}/org` | | 200 `OrgChart` | Snapshot as of `as_of_event_id` |
| `GET /api/v1/runs/{run_id}/ledger` | | 200 `LedgerView` | Predicted versus real, every `LedgerEntry` (with `usage_estimated`), stopped scopes |
| `GET /api/v1/runs/{run_id}/tasks` | | 200 `TaskList` | Each `TaskV1`, its `ResultV1`, attempt records and label |
| `GET /api/v1/runs/{run_id}/messages` | | 200 `ChatMessageList` | Chat with the director (or the VP with a board) |
| `POST /api/v1/runs/{run_id}/messages` | `PostMessageRequest` | 202 `ChatMessageList` (the new user message) | The answer arrives as a `message` event |
| `POST /api/v1/runs/{run_id}/approval` | `ApprovalRequest` | 202 `RunView` | Only while `status` is `awaiting_approval` (flow step 4) |
| `POST /api/v1/runs/{run_id}/pause` | | 202 `RunView` | The user's brake: pending calls are frozen |
| `POST /api/v1/runs/{run_id}/resume` | | 202 `RunView` | |
| `POST /api/v1/runs/{run_id}/cancel` | | 202 `RunView` | See "Cancellation" |
| `GET /api/v1/runs/{run_id}/package` | | 200 `DeliveryPackage`, or 409 `package_not_ready` | Summary, deliverables, cost report, contracts, decisions, audit verdict |

Run `status` values: `queued`, `planning`, `awaiting_approval`, `running`, `paused`, `finished`, `failed`, `cancelled`. In a recorded run, `POST /messages`, `/approval`, `/pause` and `/resume` return 409 `recorded_run` (the replay cannot change); `/cancel` stops the replay.

Agent levels (`AgentNode.level`) are the ledger's levels: `vp`, `director`, `manager`, `operator`, `auditor`. Attempt records (`AttemptRecord`) are exactly the harness's: `reason` is `first`, `repair` (a retry on the same model) or `escalation` (the next model on the ladder), and a task's `label` is `first_pass_ok`, `ok_after_retry`, `ok_after_escalation` or `failed`. The UI shows "first pass", "retry" and "escalation" from these two fields.

## Live feed (Server-Sent Events)

`GET /api/v1/runs/{run_id}/events` answers with:

```
HTTP/1.1 200 OK
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

The stream starts with `retry: 3000` (reconnect after 3 s). Each event is one frame, with the JSON on a single `data:` line:

```
id: run_8f2c1a7d4b:12
event: tool_called
data: {"id": "run_8f2c1a7d4b:12", "seq": 12, "run_id": "run_8f2c1a7d4b", "mode": "recorded", "ts": "...", "type": "tool_called", "payload": {...}}

```

A comment line `: keep-alive` is sent every 15 s without events. Every event has the same envelope (`id`, `seq`, `run_id`, `ts`, `type`, `payload`); the schema of the whole union is `docs/api/schemas/SseEvent.json`, with `type` as the discriminator.

### Ordering and idempotency

- `seq` starts at 1 and grows by 1 per event within a run; `id` is `<run_id>:<seq>`; `ts` never goes back.
- `run_started` is first. Exactly one terminal event, `run_finished` or `run_failed`, is last; the server then closes the stream.
- `agent_hired` comes before any event that names its `agent_id`. For a task: `task_assigned`, then per attempt `task_started`, the attempt's `tool_called` events and `attempt_recorded`, then `task_result`.
- A `budget_update` follows each charged ledger entry (`payload.entry`). Its numbers are absolute totals, not deltas, and every payload is a full snapshot of what it describes, so applying an event twice is harmless. Clients deduplicate by `id`.
- Resume: on reconnect the browser sends `Last-Event-ID`; clients that cannot set headers pass `?last_event_id=`. The server resends every event with a larger `seq`, in order. An id from another run gets 400 `invalid_last_event_id`. When the run already ended and the client has its terminal event, the server answers 204 (an `EventSource` then stops reconnecting).
- Recorded runs replay the stored events with their original `seq`, payloads and delays; the server rewrites `run_id` and `id` to the new run.

### Event catalog

Every example below is copied from the synthetic fixtures and validated by `tests/test_api_contract.py`. Numbers are arithmetic on `config/prices.json`, not measurements.

| `type` | Sent when | Payload |
|---|---|---|
| `run_started` | The run begins | Goal, mode, recording, budget, board, simulated case |
| `agent_hired` | An agent joins the org chart | `AgentNode` |
| `task_assigned` | A manager hands a task to an operator | `TaskV1`, agent and operator ids |
| `task_started` | An attempt starts (first, repair or escalation) | Task, agent, model, `attempt_index` |
| `attempt_recorded` | An attempt ends | `AttemptRecord` (reason, validation errors, cost, `usage_estimated`) |
| `tool_called` | A tool ran inside an attempt | Tool name, ok or error type, run count; `args` only in debug |
| `budget_update` | A ledger entry was charged | Absolute totals and the `LedgerEntry` |
| `message` | The director (or VP) or the user wrote in the chat | `ChatMessage` |
| `task_result` | A task finished | `ResultV1` and its label |
| `audit_result` | The auditor judged the deliverable | `AuditVerdict` |
| `run_finished` | The run ended normally or was cancelled | Status, partial, spent and predicted USD, package URL |
| `run_failed` | The run ended with an error | `ErrorBody`, partial, spent USD |
| `mode_notice` | Something about the mode the user should see | `recorded_mode`, `live_refused` or `live_cap_warning` |

#### `run_started`

```json
{
  "id": "run_8f2c1a7d4b:1",
  "seq": 1,
  "run_id": "run_8f2c1a7d4b",
  "mode": "recorded",
  "ts": "2026-10-20T15:00:00Z",
  "type": "run_started",
  "payload": {
    "goal": "[synthetic] Plan a one-page website for a simulated corner bakery.",
    "mode": "recorded",
    "recording_id": "rec-demo-bakery-001",
    "budget_usd": 0.25,
    "board": false,
    "simulated_case": true
  }
}
```

#### `agent_hired`

```json
{
  "id": "run_8f2c1a7d4b:3",
  "seq": 3,
  "run_id": "run_8f2c1a7d4b",
  "mode": "recorded",
  "ts": "2026-10-20T15:00:00.350000Z",
  "type": "agent_hired",
  "payload": {
    "agent": {
      "agent_id": "a-director",
      "level": "director",
      "role": "director",
      "model": "nemotron-3-ultra",
      "operator_id": null,
      "parent_id": null,
      "skills": [],
      "tools": [],
      "status": "hired"
    }
  }
}
```

#### `task_assigned`

```json
{
  "id": "run_8f2c1a7d4b:10",
  "seq": 10,
  "run_id": "run_8f2c1a7d4b",
  "mode": "recorded",
  "ts": "2026-10-20T15:00:05.950000Z",
  "type": "task_assigned",
  "payload": {
    "task": {
      "task_id": "t-1",
      "run_id": "run_8f2c1a7d4b",
      "role": "researcher",
      "instruction_ref": "store://run_8f2c1a7d4b/briefs/t-1",
      "inputs": [],
      "budget": {
        "max_input_tokens": 20000,
        "max_output_tokens": 4000,
        "max_usd": 0.01
      },
      "deadline_s": 120
    },
    "agent_id": "a-op-research",
    "operator_id": "researcher-lightning-01"
  }
}
```

#### `task_started`

```json
{
  "id": "run_8f2c1a7d4b:11",
  "seq": 11,
  "run_id": "run_8f2c1a7d4b",
  "mode": "recorded",
  "ts": "2026-10-20T15:00:06.050000Z",
  "type": "task_started",
  "payload": {
    "task_id": "t-1",
    "agent_id": "a-op-research",
    "model": "nemotron-3.5-lightning",
    "attempt_index": 0
  }
}
```

#### `attempt_recorded`

Example (first):

```json
{
  "id": "run_8f2c1a7d4b:13",
  "seq": 13,
  "run_id": "run_8f2c1a7d4b",
  "mode": "recorded",
  "ts": "2026-10-20T15:00:07.650000Z",
  "type": "attempt_recorded",
  "payload": {
    "agent_id": "a-op-research",
    "attempt": {
      "task_id": "t-1",
      "attempt_index": 0,
      "model": "nemotron-3.5-lightning",
      "protocol": "native_tools",
      "reason": "first",
      "retry_reason": null,
      "loop_status": "final",
      "ok": true,
      "validation_errors": [],
      "length_retries": 0,
      "steps": 2,
      "model_calls": 2,
      "tool_calls": {
        "search": 1
      },
      "usd": 0.0001728,
      "input_tokens": 2000,
      "output_tokens": 220,
      "usage_estimated": false,
      "detail": ""
    }
  }
}
```

Example (repair):

```json
{
  "id": "run_8f2c1a7d4b:22",
  "seq": 22,
  "run_id": "run_8f2c1a7d4b",
  "mode": "recorded",
  "ts": "2026-10-20T15:00:10.600000Z",
  "type": "attempt_recorded",
  "payload": {
    "agent_id": "a-op-copy",
    "attempt": {
      "task_id": "t-2",
      "attempt_index": 1,
      "model": "nemotron-3.5-lightning",
      "protocol": "native_tools",
      "reason": "repair",
      "retry_reason": "validation_failed",
      "loop_status": "final",
      "ok": false,
      "validation_errors": [
        "output.body: String should have at most 600 characters"
      ],
      "length_retries": 0,
      "steps": 1,
      "model_calls": 1,
      "tool_calls": {},
      "usd": 0.00015,
      "input_tokens": 1300,
      "output_tokens": 300,
      "usage_estimated": false,
      "detail": ""
    }
  }
}
```

Example (escalation):

```json
{
  "id": "run_8f2c1a7d4b:28",
  "seq": 28,
  "run_id": "run_8f2c1a7d4b",
  "mode": "recorded",
  "ts": "2026-10-20T15:00:13.200000Z",
  "type": "attempt_recorded",
  "payload": {
    "agent_id": "a-op-copy",
    "attempt": {
      "task_id": "t-2",
      "attempt_index": 3,
      "model": "nemotron-3-super",
      "protocol": "native_tools",
      "reason": "escalation",
      "retry_reason": "interrupted",
      "loop_status": "final",
      "ok": true,
      "validation_errors": [],
      "length_retries": 0,
      "steps": 1,
      "model_calls": 1,
      "tool_calls": {},
      "usd": 0.000615,
      "input_tokens": 1000,
      "output_tokens": 350,
      "usage_estimated": false,
      "detail": ""
    }
  }
}
```

#### `tool_called`

```json
{
  "id": "run_8f2c1a7d4b:12",
  "seq": 12,
  "run_id": "run_8f2c1a7d4b",
  "mode": "recorded",
  "ts": "2026-10-20T15:00:06.750000Z",
  "type": "tool_called",
  "payload": {
    "task_id": "t-1",
    "agent_id": "a-op-research",
    "tool": "search",
    "ok": true,
    "error_type": null,
    "truncated": false,
    "run_tool_count": 1,
    "args": null
  }
}
```

#### `budget_update`

```json
{
  "id": "run_8f2c1a7d4b:4",
  "seq": 4,
  "run_id": "run_8f2c1a7d4b",
  "mode": "recorded",
  "ts": "2026-10-20T15:00:02.150000Z",
  "type": "budget_update",
  "payload": {
    "spent_usd": 0.0048,
    "held_usd": 0.0,
    "predicted_usd": 0.005,
    "cap_usd": 0.25,
    "spent_by_level": {
      "director": 0.0048
    },
    "entry": {
      "run_id": "run_8f2c1a7d4b",
      "level": "director",
      "task_id": "plan",
      "model": "nemotron-3-ultra",
      "input_tokens": 3000,
      "cached_tokens": 0,
      "output_tokens": 600,
      "reasoning_tokens": 0,
      "cached_price_fallback": true,
      "usd_real": 0.0048,
      "usd_predicted": 0.005,
      "ts": "2026-10-20T15:00:00.350000Z",
      "skills": [],
      "usage_estimated": false
    }
  }
}
```

#### `message`

```json
{
  "id": "run_8f2c1a7d4b:5",
  "seq": 5,
  "run_id": "run_8f2c1a7d4b",
  "mode": "recorded",
  "ts": "2026-10-20T15:00:02.250000Z",
  "type": "message",
  "payload": {
    "message": {
      "message_id": "m-1",
      "run_id": "run_8f2c1a7d4b",
      "sender": "director",
      "text": "[synthetic] Plan: one manager, a researcher and a copywriter, within the USD 0.25 cap. Approve?",
      "ts": "2026-10-20T15:00:02.250000Z"
    }
  }
}
```

#### `task_result`

```json
{
  "id": "run_8f2c1a7d4b:15",
  "seq": 15,
  "run_id": "run_8f2c1a7d4b",
  "mode": "recorded",
  "ts": "2026-10-20T15:00:07.750000Z",
  "type": "task_result",
  "payload": {
    "agent_id": "a-op-research",
    "result": {
      "task_id": "t-1",
      "status": "ok",
      "output_ref": "store://run_8f2c1a7d4b/results/t-1",
      "usage": {
        "input_tokens": 2000,
        "output_tokens": 220,
        "usd": 0.0001728
      },
      "self_check": {
        "schema_valid": true,
        "notes": "first_pass_ok"
      }
    },
    "label": "first_pass_ok"
  }
}
```

#### `audit_result`

```json
{
  "id": "run_8f2c1a7d4b:32",
  "seq": 32,
  "run_id": "run_8f2c1a7d4b",
  "mode": "recorded",
  "ts": "2026-10-20T15:00:15Z",
  "type": "audit_result",
  "payload": {
    "audit": {
      "verdict": "accepted",
      "model": "nemotron-3-ultra",
      "checks": [
        {
          "criterion": "[synthetic] Covers the goal",
          "passed": true,
          "note": ""
        },
        {
          "criterion": "[synthetic] Plain, specific prose",
          "passed": true,
          "note": ""
        },
        {
          "criterion": "[synthetic] Sources listed",
          "passed": true,
          "note": ""
        }
      ],
      "correction_cycles": 0,
      "warning": null
    }
  }
}
```

#### `run_finished`

```json
{
  "id": "run_8f2c1a7d4b:36",
  "seq": 36,
  "run_id": "run_8f2c1a7d4b",
  "mode": "recorded",
  "ts": "2026-10-20T15:00:16.250000Z",
  "type": "run_finished",
  "payload": {
    "status": "finished",
    "partial": false,
    "spent_usd": 0.013171559999999999,
    "predicted_usd": 0.013499999999999998,
    "package_url": "/api/v1/runs/run_8f2c1a7d4b/package"
  }
}
```

#### `run_failed`

```json
{
  "id": "run_3e9d0b6a51:2",
  "seq": 2,
  "run_id": "run_3e9d0b6a51",
  "mode": "live",
  "ts": "2026-10-20T16:00:00.020000+00:00",
  "type": "run_failed",
  "payload": {
    "error": {
      "code": "live_refused",
      "message": "[synthetic] Live budget for today is used up.",
      "details": {
        "refusal": "daily_cap_reached"
      }
    },
    "partial": false,
    "spent_usd": 0.0
  }
}
```

#### `mode_notice`

```json
{
  "id": "run_8f2c1a7d4b:2",
  "seq": 2,
  "run_id": "run_8f2c1a7d4b",
  "mode": "recorded",
  "ts": "2026-10-20T15:00:00.050000Z",
  "type": "mode_notice",
  "payload": {
    "notice": "recorded_mode",
    "mode": "recorded",
    "refusal": null,
    "detail": "Replaying a saved synthetic run. It costs nothing."
  }
}
```

Example (live_refused):

```json
{
  "id": "run_3e9d0b6a51:1",
  "seq": 1,
  "run_id": "run_3e9d0b6a51",
  "mode": "live",
  "ts": "2026-10-20T16:00:00+00:00",
  "type": "mode_notice",
  "payload": {
    "notice": "live_refused",
    "mode": "live",
    "refusal": "daily_cap_reached",
    "detail": "[synthetic] The daily live budget ran out before this run started. Nothing was spent."
  }
}
```

## Errors

Every non-2xx response has the body `ErrorResponse`:

```json
{"error": {"code": "live_refused", "message": "Live runs are paused: the daily live budget is used up.", "details": {"refusal": "daily_cap_reached"}, "request_id": "req-1"}}
```

| HTTP | `code` | When |
|---|---|---|
| 400 | `bad_request`, `invalid_last_event_id` | Malformed JSON; a `Last-Event-ID` from another run |
| 404 | `not_found` | Unknown run, recording or path |
| 409 | `package_not_ready`, `run_not_active`, `not_awaiting_approval`, `recorded_run` | The run is not in a state that allows the request |
| 422 | `validation_failed`, `live_refused` (with `refusal: run_cap_exceeded`) | The body does not match its schema (`details.errors` lists them); budget above the per-run cap |
| 429 | `live_refused` (with `refusal: daily_cap_reached` or `visitor_limit_reached`) | Live caps; `Retry-After` header in seconds |
| 500 | `internal_error` | Unexpected; the body never carries a traceback |
| 503 | `live_refused` (with `refusal: live_disabled`) | Live mode is off |

`details` is an object whose keys depend on `code`; `request_id` matches the `X-Request-Id` response header.

## Cancellation

`POST /api/v1/runs/{run_id}/cancel` returns 202 with the run. The server stops sending model calls; calls in flight are cancelled and settled by the harness (a call already sent and cut off is charged under `on_missing_usage`, marked `usage_estimated: true`). The stream then ends with `run_finished` with `status: "cancelled"` and `partial: true`, after a final `budget_update`. Cancelling a finished run returns 409 `run_not_active`.

## What the UI never receives

- API keys, tokens, `Authorization` headers, environment values, Tavily keys.
- Raw prompts: system prompts, skill texts, the message histories sent to models, and tool arguments. v1 has no endpoint that serves prompts.
- Model internals: reasoning text, streamed deltas, request bodies, cassettes, rate-limit headers, tracebacks.

Debug flag: when the server runs with `ROOKWISE_API_DEBUG=1` and the client adds `?debug=1` to the events URL, `tool_called` events carry `args` (the tool arguments). Nothing else changes. The public deployment never sets the flag. Fixtures never carry `args`.

## Not in core yet

Everything below is defined by this contract only; `core/` has no field, model or code for it yet (Stage 3 builds it):

- Runs: `goal`, `mode`, `recording_id`, `simulated_case`, `status`, `board`, `created_at`, `finished_at`, `events_url`; the run list and its `next_cursor`. (`run_id`, the caps `run_usd` and `level_usd`, and `spent_usd` and `held_usd` exist in the ledger.)
- `predicted_usd` (per run, in `LedgerView`, `BudgetUpdatePayload`, `RunFinishedPayload`) and `usage_estimated_entries`: sums over the ledger entries' existing `usd_predicted` and `usage_estimated`, not computed anywhere in core yet.
- Modes and caps: all of `ModesView`, `ModeAvailability`, `RefusalReason`, `LiveCaps` (the two USD caps exist only as `.env.example` variables that no code reads), `spent_usd_today`, `max_runs_per_visitor_per_day`, `visitor_runs_today`, `RecordingSummary`.
- Org chart: `agent_id`, `parent_id`, agent `status`, `as_of_event_id`. (`level` is `rookwise.schemas.Level`; `role`, `model`, `operator_id`, `skills` and `tools` are catalog fields of `OperatorSpec`.)
- Chat: all of `ChatMessage` and the approval request.
- Tasks: `TaskView.agent_id` and task `status`. (`label`, `attempts` and `tool_calls` come from the runner.)
- Delivery package: `summary`, `Deliverable`, `CostReport` (the `prediction_error` metric is defined in docs/ARCHITECTURE.md but not computed in code), `ContractRecord`, `decisions`, and the whole `AuditVerdict` (there is no auditor yet).
- Events: the envelope (`id`, `seq`, `ts`, `type`) and every payload wrapper. Per-call `tool_called` events do not exist: the tool loop keeps a trace (`kind`, `tool`, `ok`) and a count per tool, but not `error_type` or `truncated` per call, and `run_tool_count` would be a run-wide counter. `task_started.attempt_index` is the `AttemptRecord.attempt_index`.
- Errors: `ErrorBody` and its codes; pause, resume and approval; the debug flag; visitor identification.

## Open points

- How the server identifies a visitor for `visitor_limit_reached` (cookie, header or IP hash) and the limit itself.
- Whether recorded mode replays stored event logs (as above) or re-executes runs through harness cassettes.
- Whether SSE fits the hosting plan (Vercel function duration limits are UNVERIFIED).
