# Mock server for the API v1 (frontend without the backend)

`examples/api/mock/serve.py` serves the synthetic fixtures in `examples/api/` with the routes, status codes, headers and event stream described in [docs/api.md](api.md), so `web/` can be built before the server exists. It uses the Python standard library only (Python 3.11, already required by the project).

Everything it returns is **synthetic**: written by `scripts/gen_api_fixtures.py`, not model output, and marked `[synthetic]` in every visible text. Never present it as a real run.

## Run it

```bash
python examples/api/mock/serve.py
```

Options: `--port 8787` (default), `--host 127.0.0.1` (default), `--speed 1` (replay at the recorded pace; `4` is four times faster; `0` sends every event at once). The base URL is `http://127.0.0.1:8787/api/v1`. CORS is open (`Access-Control-Allow-Origin: *`) so a dev server on another port can call it.

## What it serves

| Request | Answer |
|---|---|
| `GET /modes` | `recorded_run.json` `modes` (live available) |
| `GET /runs` | `recorded_run.json` `runs` |
| `POST /runs` with `{"mode": "recorded", "recording_id": "rec-demo-bakery-001"}` | 201, the recorded run (`r-demo-001`) |
| `POST /runs` with `{"mode": "live", ...}` | 429 with `Retry-After: 3600` and the `live_refused` error from `live_refused.json`, so the refusal UI can be built |
| `POST /runs` with anything else | 422 `validation_failed` |
| `GET /runs/r-demo-001` and `/org`, `/ledger`, `/tasks`, `/messages`, `/package` | The matching section of `recorded_run.json` |
| `GET /runs/r-demo-001/events` | The SSE replay of `recorded_run.events.json` |
| `GET /runs/r-demo-002/events` | A live run refused after creation: `mode_notice` (`live_refused`), then `run_failed` |
| `POST /runs/r-demo-001/cancel` | 202 with the run |
| `POST /runs/r-demo-001/messages`, `/approval`, `/pause`, `/resume` | 409 `recorded_run` |
| Anything else | 404 `not_found` |

Every response carries `X-Request-Id`; error bodies follow `ErrorResponse`.

## The event stream

Headers: `Content-Type: text/event-stream; charset=utf-8`, `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`. The stream starts with `retry: 3000`, then sends one frame per event, waiting `delay_ms` (divided by `--speed`) before each:

```
id: r-demo-001:12
event: tool_called
data: {"id": "r-demo-001:12", "seq": 12, ...}

```

A `: keep-alive` comment goes out every 15 s during long waits. After the terminal event (`run_finished` or `run_failed`) the server closes the connection.

Resume behaves as in the contract:

- `Last-Event-ID: r-demo-001:10` (sent by the browser's `EventSource` on reconnect) or `?last_event_id=r-demo-001:10` replays from `seq` 11.
- An id at or after the terminal event returns 204, which makes `EventSource` stop reconnecting.
- An id from another run returns 400 `invalid_last_event_id`.

To try a reconnect: open the stream at `--speed 1`, stop it after a few events, and reopen it with the last id you received.

In the browser:

```js
const source = new EventSource("http://127.0.0.1:8787/api/v1/runs/r-demo-001/events");
source.addEventListener("budget_update", (e) => render(JSON.parse(e.data)));
source.addEventListener("run_finished", () => source.close());
```

Listen with `addEventListener(<type>)`: every frame has an `event:` name, so `onmessage` alone receives nothing.

## Keeping it honest

- `tests/test_api_mock.py` starts the mock on localhost and checks the routes, the refusal, the SSE headers, framing, order and Last-Event-ID resume against the fixtures.
- `tests/test_api_contract.py` validates every fixture against the contract models and checks that the committed JSON Schemas match them.
- After a contract change: edit `core/api/models.py`, then run `python scripts/gen_api_schemas.py` and `python scripts/gen_api_fixtures.py`, and update `docs/api.md`.
