"""Mock of the Rookwise API v1 for frontend work without the backend (docs/api-mock.md).

Serves the SYNTHETIC fixtures in examples/api/ and replays the event stream as
Server-Sent Events with the documented headers, ids and Last-Event-ID resume. Python
standard library only.

    python examples/api/mock/serve.py                # http://127.0.0.1:8787
    python examples/api/mock/serve.py --speed 4      # replay four times faster
    python examples/api/mock/serve.py --speed 0      # no delays at all
    python examples/api/mock/serve.py --recording examples/api/recordings/inc-03-run2

Everything it returns is synthetic (see `_fixture` in each fixture file), except a
recording passed with --recording: a real run on a synthetic incident, exported by
scripts/export_recorded_run.py (see `_recording` in its files). It is listed first in
GET /modes and served next to the synthetic run.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from collections.abc import Sequence
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

FIXTURES = Path(__file__).resolve().parent.parent
PREFIX = "/api/v1"
HEARTBEAT_S = 15.0
TERMINAL = ("run_finished", "run_failed")


RUN_SECTIONS = ("run", "org", "ledger", "messages", "tasks", "package")


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _created(run: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))


class Fixtures:
    """The synthetic fixtures, plus any exported recordings (scripts/export_recorded_run.py).
    Run-scoped routes are looked up by run_id, so two recordings must not share one."""

    def __init__(self, recordings: Sequence[Path] = ()) -> None:
        self.bundle = _read(FIXTURES / "recorded_run.json")
        replay = _read(FIXTURES / "recorded_run.events.json")
        self.refused = _read(FIXTURES / "live_refused.json")
        self.run_id = self.bundle["run"]["run_id"]
        refused_run = self.refused["refused_after_creation"]
        self.streams = {
            self.run_id: replay["events"],
            refused_run["run_id"]: refused_run["events"],
        }
        self.runs = {self.run_id: self.bundle}  # recorded runs: run_id -> bundle
        self.recordings = {
            r["recording_id"]: self.run_id for r in self.bundle["modes"]["recordings"]
        }
        summaries = []
        for folder in recordings:
            bundle = _read(Path(folder) / "recorded_run.json")
            events = _read(Path(folder) / "recorded_run.events.json")["events"]
            missing = [s for s in ("_recording", "recording", *RUN_SECTIONS) if s not in bundle]
            if missing:
                raise ValueError(f"{folder} is not an exported recording (missing {missing})")
            run_id = bundle["run"]["run_id"]
            recording_id = bundle["recording"]["recording_id"]
            if run_id in self.streams or recording_id in self.recordings:
                raise ValueError(f"{folder}: run {run_id} or {recording_id} is already served")
            self.runs[run_id] = bundle
            self.streams[run_id] = events
            self.recordings[recording_id] = run_id
            summaries.append(bundle["recording"])
        modes = self.bundle["modes"]
        self.modes = {**modes, "recordings": summaries + modes["recordings"]}
        newest_first = sorted((b["run"] for b in self.runs.values()), key=_created, reverse=True)
        self.run_list = {"items": newest_first, "next_cursor": None}


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
            if parts == ["modes"]:
                return self._json(200, fixtures.modes)
            if parts == ["runs"]:
                return self._json(200, fixtures.run_list)
            if len(parts) >= 2 and parts[0] == "runs":
                run_id = parts[1]
                if len(parts) == 3 and parts[2] == "events" and run_id in fixtures.streams:
                    return self._events(run_id)
                bundle = fixtures.runs.get(run_id)
                if bundle is not None:
                    views = {
                        (): "run",
                        ("org",): "org",
                        ("ledger",): "ledger",
                        ("tasks",): "tasks",
                        ("messages",): "messages",
                        ("package",): "package",
                    }
                    section = views.get(tuple(parts[2:]))
                    if section is not None and bundle[section] is None:
                        return self._error(
                            409, "package_not_ready", "this run has no delivery package"
                        )
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
                run_id = fixtures.recordings.get(body.get("recording_id"))
                if body.get("mode") == "recorded" and run_id is not None:
                    return self._json(201, fixtures.runs[run_id]["run"])
                return self._error(
                    422,
                    "validation_failed",
                    "see docs/api.md, POST /runs",
                    errors=["mode: 'live' or 'recorded' with a known recording_id"],
                )
            if len(parts) == 3 and parts[0] == "runs":
                if parts[2] in ("pause", "resume"):
                    return self._error(
                        501, "not_implemented", f"{parts[2]} is reserved until core supports it"
                    )
                if parts[1] in fixtures.runs and parts[2] in ("messages", "approval", "cancel"):
                    return self._error(
                        409, "recorded_run", "a recorded run cannot be changed; close the stream"
                    )
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


def make_server(
    host: str = "127.0.0.1",
    port: int = 8787,
    speed: float = 1.0,
    recordings: Sequence[Path] = (),
):
    return ThreadingHTTPServer((host, port), make_handler(Fixtures(recordings), speed))


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the synthetic API v1 fixtures.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--speed", type=float, default=1.0, help="replay speed factor; 0 sends every event at once"
    )
    parser.add_argument(
        "--recording",
        type=Path,
        action="append",
        default=[],
        metavar="PATH",
        help="an exported recording folder (scripts/export_recorded_run.py); repeatable",
    )
    args = parser.parse_args()
    server = make_server(args.host, args.port, args.speed, args.recording)
    print(f"Rookwise API v1 mock (synthetic fixtures) on http://{args.host}:{args.port}{PREFIX}")
    for folder in args.recording:
        print(f"  also serving the recording in {folder}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
