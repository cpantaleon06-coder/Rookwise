# Mock server for the API v1 (frontend without the backend)

`examples/api/mock/serve.py` serves the synthetic fixtures in `examples/api/` with the routes, status codes, headers and event stream described in [docs/api.md](api.md), so `web/` can be built before the server exists. It uses the Python standard library only (Python 3.11, already required by the project).

Without `--recording`, everything it returns is **synthetic**: written by `scripts/gen_api_fixtures.py`, not model output, and marked `[synthetic]` in every visible text. Never present it as a real run. Every payload of the recorded run carries `mode: "recorded"`; show that label in the UI. Money comes as six-decimal strings (`"0.004800"`), as in the contract (docs/api.md, "Conventions"); do not turn it into JavaScript numbers for arithmetic.

The mock sets no visitor cookie and serves everything from one origin with `Access-Control-Allow-Origin: *`, so it cannot exercise the cross-host cookie rules in docs/api.md ("Visitors"); test those against the real server.

## Run it

```bash
python examples/api/mock/serve.py
```

Options: `--port 8787` (default), `--host 127.0.0.1` (default), `--speed 1` (replay at the recorded pace; `4` is four times faster; `0` sends every event at once), `--recording PATH` (serve an exported recording too; repeatable, see below). The base URL is `http://127.0.0.1:8787/api/v1`. CORS is open (`Access-Control-Allow-Origin: *`) so a dev server on another port can call it.

## Serving a real recorded run

`scripts/export_recorded_run.py` turns a run folder written by `scripts/run_incident.py` (`report.json`, `events.json`, `calls.json`) into a recording folder with `recorded_run.json` and `recorded_run.events.json` (docs/api.md, "Changes on 2026-10-25"). Serve it next to the synthetic run:

```bash
python examples/api/mock/serve.py --recording examples/api/recordings/inc-03-run2
```

Unlike the fixtures, a recording is a **real run** (model output) on a **synthetic incident**: its `_recording` header says so, lists what the export changed (`mode`, `recording_id`, `package_url`, `tool_called.args`) and lists under `not_filled` what the run folder did not keep (those fields are `null` or empty, never invented). The two committed recordings carry their full diagnosis (root cause, claims in order with citations, evidence check, remediation plan, empty sources), recovered by `tools/recover_diagnosis.py` from an offline replay of each run's cassette (`_recording.diagnosis_source`). Label it as recorded, and as a synthetic incident, like any recorded run.

With `--recording`:

| Request | Answer |
|---|---|
| `GET /modes` | The fixture's `modes`, with each recording's `RecordingSummary` listed first, in the order given, then the synthetic one |
| `GET /runs` | Every recorded run (each recording and the synthetic run), newest `created_at` first |
| `POST /runs` with `{"mode": "recorded", "recording_id": "<its recording_id>"}` | 201, that recording's run |
| `GET /runs/{its run_id}` and `/org`, `/ledger`, `/tasks`, `/messages`, `/package` | The matching section of its `recorded_run.json`; `/package` is 409 `package_not_ready` when the run had no audit (for example a run that failed at its plan) |
| `GET /runs/{its run_id}/events` | The SSE replay of its `recorded_run.events.json`, with the same headers, framing and `Last-Event-ID` resume as the synthetic run |
| `POST /runs/{its run_id}/messages`, `/approval`, `/cancel` | 409 `recorded_run` |

The mock routes by `run_id`, so it refuses to start with two recordings of the same run id (all runs of one incident share one, for example `run_inc01`); serve one of them at a time. A recording's stream has no `mode_notice` (`recorded_mode`) first: the live run did not emit one, and adding it would change the original event ids; the recorded banner then uses its fixed line (web/DESIGN.md 3.3). The export caps each delay at 1.5 s, so a 12-minute run replays in about two minutes at `--speed 1`.

## What it serves

| Request | Answer |
|---|---|
| `GET /modes` | `recorded_run.json` `modes` (live available) |
| `GET /runs` | `recorded_run.json` `runs` |
| `POST /runs` with `{"mode": "recorded", "recording_id": "rec-demo-bakery-001"}` | 201, the recorded run (`run_8f2c1a7d4b`) |
| `POST /runs` with `{"mode": "live", ...}` | 429 with `Retry-After: 3600` and the `live_refused` error from `live_refused.json` (daily cap), so the refusal UI can be built. There is no automatic fallback: the UI offers a recorded run as a separate user action |
| `POST /runs` with anything else | 422 `validation_failed` |
| `GET /runs/run_8f2c1a7d4b` and `/org`, `/ledger`, `/tasks`, `/messages`, `/package` | The matching section of `recorded_run.json` |
| `GET /runs/run_8f2c1a7d4b/events` | The SSE replay of `recorded_run.events.json` |
| `GET /runs/run_3e9d0b6a51/events` | A live run refused after creation: `mode_notice` (`live_refused`), then `run_failed` |
| `POST /runs/run_8f2c1a7d4b/messages`, `/approval`, `/cancel` | 409 `recorded_run` (a recording cannot change; close the stream to stop watching) |
| `POST /runs/{any}/pause`, `/resume` | 501 `not_implemented` (reserved until core supports them; the UI shows cancel only) |
| Anything else | 404 `not_found` |

Every response carries `X-Request-Id`; error bodies follow `ErrorResponse`.

## The event stream

Headers: `Content-Type: text/event-stream; charset=utf-8`, `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`. The stream starts with `retry: 3000`, then sends one frame per event, waiting `delay_ms` (divided by `--speed`) before each:

```
id: run_8f2c1a7d4b:16
event: tool_called
data: {"id": "run_8f2c1a7d4b:16", "seq": 16, ...}

```

A `: keep-alive` comment goes out every 15 s during long waits. After the terminal event (`run_finished` or `run_failed`) the server closes the connection.

Resume behaves as in the contract:

- `Last-Event-ID: run_8f2c1a7d4b:10` (sent by the browser's `EventSource` on reconnect) or `?last_event_id=run_8f2c1a7d4b:10` replays from `seq` 11.
- An id at or after the terminal event returns 204, which makes `EventSource` stop reconnecting.
- An id from another run returns 400 `invalid_last_event_id`.

To try a reconnect: open the stream at `--speed 1`, stop it after a few events, and reopen it with the last id you received.

In the browser:

```js
const source = new EventSource("http://127.0.0.1:8787/api/v1/runs/run_8f2c1a7d4b/events");
source.addEventListener("budget_update", (e) => render(JSON.parse(e.data)));
source.addEventListener("run_finished", () => source.close());
```

Listen with `addEventListener(<type>)`: every frame has an `event:` name, so `onmessage` alone receives nothing.

## Keeping it honest

- `tests/test_api_mock.py` starts the mock on localhost and checks the routes, the refusal, the SSE headers, framing, order and Last-Event-ID resume against the fixtures.
- `tests/test_api_mock_recording.py` does the same with two recordings exported from small synthetic run folders, and `tests/test_export_recorded_run.py` checks the export itself.
- `tests/test_api_contract.py` validates every fixture against the contract models and checks that the committed JSON Schemas match them.
- After a contract change: edit `core/api/models.py`, then run `python scripts/gen_api_schemas.py` and `python scripts/gen_api_fixtures.py`, and update `docs/api.md`.
