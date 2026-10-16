"""Mock of the Rookwise API v1 for frontend work without the backend (docs/api-mock.md).

Serves the SYNTHETIC fixtures in examples/api/ and replays the event stream as
Server-Sent Events with the documented headers, ids and Last-Event-ID resume. Python
standard library only.

    python examples/api/mock/serve.py                # http://127.0.0.1:8787
    python examples/api/mock/serve.py --speed 4      # replay four times faster
    python examples/api/mock/serve.py --speed 0      # no delays at all

Everything it returns is synthetic (see `_fixture` in each fixture file).
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

FIXTURES = Path(__file__).resolve().parent.parent
PREFIX = "/api/v1"
HEARTBEAT_S = 15.0
TERMINAL = ("run_finished", "run_failed")


def _read(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Fixtures:
    def __init__(self) -> None:
        self.bundle = _read("recorded_run.json")
        replay = _read("recorded_run.events.json")
        self.refused = _read("live_refused.json")
        self.run_id = self.bundle["run"]["run_id"]
        refused_run = self.refused["refused_after_creation"]
        self.streams = {
            self.run_id: replay["events"],
            refused_run["run_id"]: refused_run["events"],
        }
        self.recording_ids = {r["recording_id"] for r in self.bundle["modes"]["recordings"]}


def make_handler(fixtures: Fixtures, speed: float) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "RookwiseMock/1"
        protocol_version = "HTTP/1.1"

        # -- helpers -------------------------------------------------------------------

        def _common_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("X-Request-Id", self.request_id)

        def _json(self, status: int, body: Any, headers: dict[str, str] | None = None) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self._common_headers()
            self.end_headers()
            self.wfile.write(data)

        def _error(self, status: int, code: str, message: str, **details: Any) -> None:
            self._json(
                status,
                {
                    "error": {
                        "code": code,
                        "message": message,
                        "details": details,
                        "request_id": self.request_id,
                    }
                },
            )

        def _route(self) -> list[str]:
            path = urlparse(self.path).path.rstrip("/")
            if not path.startswith(PREFIX):
                return []
            return [p for p in path[len(PREFIX) :].split("/") if p]

        # -- methods -------------------------------------------------------------------

        def do_OPTIONS(self) -> None:  # noqa: N802 (http.server naming)
            self.request_id = f"req-{uuid.uuid4().hex[:12]}"
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers", "Content-Type, Last-Event-ID, Idempotency-Key"
            )
            self.send_header("Content-Length", "0")
            self._common_headers()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            self.request_id = f"req-{uuid.uuid4().hex[:12]}"
            parts = self._route()
            bundle = fixtures.bundle
            if parts == ["modes"]:
                return self._json(200, bundle["modes"])
            if parts == ["runs"]:
                return self._json(200, bundle["runs"])
            if len(parts) >= 2 and parts[0] == "runs":
                run_id = parts[1]
                if len(parts) == 3 and parts[2] == "events" and run_id in fixtures.streams:
                    return self._events(run_id)
                if run_id == fixtures.run_id:
                    views = {
                        (): "run",
                        ("org",): "org",
                        ("ledger",): "ledger",
                        ("tasks",): "tasks",
                        ("messages",): "messages",
                        ("package",): "package",
                    }
                    section = views.get(tuple(parts[2:]))
                    if section is not None:
                        return self._json(200, bundle[section])
            return self._error(404, "not_found", f"no mock route for GET {self.path}")

        def do_POST(self) -> None:  # noqa: N802
            self.request_id = f"req-{uuid.uuid4().hex[:12]}"
            parts = self._route()
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            if parts == ["runs"]:
                try:
                    body = json.loads(raw or b"{}")
                except ValueError:
                    return self._error(400, "bad_request", "the body is not JSON")
                if not isinstance(body, dict):
                    return self._error(400, "bad_request", "the body must be an object")
                if body.get("mode") == "live":
                    refused = fixtures.refused
                    return self._json(
                        refused["status"], refused["response"], {"Retry-After": "3600"}
                    )
                if body.get("mode") == "recorded" and body.get("recording_id") in (
                    fixtures.recording_ids
                ):
                    return self._json(201, fixtures.bundle["run"])
                return self._error(
                    422,
                    "validation_failed",
                    "see docs/api.md, POST /runs",
                    errors=["mode: 'live' or 'recorded' with a known recording_id"],
                )
            if len(parts) == 3 and parts[0] == "runs" and parts[1] == fixtures.run_id:
                if parts[2] == "cancel":
                    return self._json(202, fixtures.bundle["run"])
                if parts[2] in ("messages", "approval", "pause", "resume"):
                    return self._error(409, "recorded_run", "a recorded run cannot be changed")
            return self._error(404, "not_found", f"no mock route for POST {self.path}")

        # -- SSE -----------------------------------------------------------------------

        def _events(self, run_id: str) -> None:
            stream = fixtures.streams[run_id]
            query = parse_qs(urlparse(self.path).query)
            last = self.headers.get("Last-Event-ID") or (query.get("last_event_id") or [""])[0]
            after = 0
            if last:
                prefix, _, seq = last.rpartition(":")
                if prefix != run_id or not seq.isdigit():
                    return self._error(
                        400, "invalid_last_event_id", f"{last!r} is not an event id of run {run_id}"
                    )
                after = int(seq)
            terminal = max(
                item["event"]["seq"] for item in stream if item["event"]["type"] in TERMINAL
            )
            if after >= terminal:
                self.send_response(HTTPStatus.NO_CONTENT)
                self.send_header("Content-Length", "0")
                self._common_headers()
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self._common_headers()
            self.end_headers()
            self.close_connection = True  # no Content-Length: the stream ends on close
            try:
                self.wfile.write(b"retry: 3000\n\n")
                self.wfile.flush()
                for item in stream:
                    event = item["event"]
                    if event["seq"] <= after:
                        continue
                    self._wait(item["delay_ms"] / 1000)
                    frame = (
                        f"id: {event['id']}\nevent: {event['type']}\n"
                        f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    )
                    self.wfile.write(frame.encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return  # the client went away; it will resume with Last-Event-ID

        def _wait(self, seconds: float) -> None:
            if speed <= 0:
                return
            remaining = seconds / speed
            while remaining > HEARTBEAT_S:
                time.sleep(HEARTBEAT_S)
                remaining -= HEARTBEAT_S
                self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
            time.sleep(remaining)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            print(f"mock {self.address_string()} {format % args}")

    return Handler


def make_server(host: str = "127.0.0.1", port: int = 8787, speed: float = 1.0):
    return ThreadingHTTPServer((host, port), make_handler(Fixtures(), speed))


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the synthetic API v1 fixtures.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--speed", type=float, default=1.0, help="replay speed factor; 0 sends every event at once"
    )
    args = parser.parse_args()
    server = make_server(args.host, args.port, args.speed)
    print(f"Rookwise API v1 mock (synthetic fixtures) on http://{args.host}:{args.port}{PREFIX}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
