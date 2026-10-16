"""The API v1 mock server (examples/api/mock/serve.py) on localhost: routes, the
refused-live answer, SSE headers, framing and Last-Event-ID resume. No outside network."""

import importlib.util
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from rookwise.api import SSE_EVENT_ADAPTER

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "examples" / "api"


def _load_serve():
    path = FIXTURES / "mock" / "serve.py"
    spec = importlib.util.spec_from_file_location("rookwise_api_mock", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def base_url():
    serve = _load_serve()
    server = serve.make_server(port=0, speed=0)
    server.log_message = lambda *a: None
    server.RequestHandlerClass.log_message = lambda *a: None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/api/v1"
    server.shutdown()
    server.server_close()


def _get(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers), response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read().decode("utf-8")


def _post(url, body):
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers), json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), json.loads(error.read())


def _frames(text):
    """Parse SSE text into (id, event, data) tuples; comments and retry lines skipped."""
    frames = []
    for block in text.split("\n\n"):
        fields = {}
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            name, _, value = line.partition(": ")
            fields[name] = value
        if "data" in fields:
            frames.append((fields["id"], fields["event"], json.loads(fields["data"])))
    return frames


def _fixture_events():
    return [
        i["event"]
        for i in json.loads((FIXTURES / "recorded_run.events.json").read_text(encoding="utf-8"))[
            "events"
        ]
    ]


def test_static_views_are_the_fixtures(base_url):
    bundle = json.loads((FIXTURES / "recorded_run.json").read_text(encoding="utf-8"))
    for path, section in (
        ("/modes", "modes"),
        ("/runs", "runs"),
        ("/runs/r-demo-001", "run"),
        ("/runs/r-demo-001/ledger", "ledger"),
        ("/runs/r-demo-001/package", "package"),
    ):
        status, headers, body = _get(base_url + path)
        assert status == 200 and json.loads(body) == bundle[section], path
        assert headers["Access-Control-Allow-Origin"] == "*"
    status, _, body = _get(base_url + "/runs/nope")
    assert status == 404 and json.loads(body)["error"]["code"] == "not_found"


def test_live_is_refused_and_recorded_is_created(base_url):
    status, headers, body = _post(
        base_url + "/runs", {"mode": "live", "goal": "x", "budget_usd": 0.1}
    )
    assert status == 429 and headers["Retry-After"] == "3600"
    assert body["error"]["code"] == "live_refused"
    assert body["error"]["details"]["refusal"] == "daily_cap_reached"
    status, _, body = _post(
        base_url + "/runs", {"mode": "recorded", "recording_id": "rec-demo-bakery-001"}
    )
    assert status == 201 and body["run_id"] == "r-demo-001"
    status, _, body = _post(base_url + "/runs/r-demo-001/messages", {"text": "hi"})
    assert status == 409 and body["error"]["code"] == "recorded_run"


def test_the_stream_has_sse_headers_and_every_event_in_order(base_url):
    status, headers, text = _get(base_url + "/runs/r-demo-001/events")
    assert status == 200
    assert headers["Content-Type"] == "text/event-stream; charset=utf-8"
    assert headers["Cache-Control"] == "no-cache"
    assert text.startswith("retry: 3000\n\n")
    frames = _frames(text)
    expected = _fixture_events()
    assert [f[2] for f in frames] == expected
    for frame_id, event_type, data in frames:
        assert frame_id == data["id"] and event_type == data["type"]
        SSE_EVENT_ADAPTER.validate_python(data)


def test_resume_with_last_event_id_header_or_query(base_url):
    expected = _fixture_events()
    _, _, text = _get(base_url + "/runs/r-demo-001/events", {"Last-Event-ID": "r-demo-001:10"})
    assert [f[2]["seq"] for f in _frames(text)] == list(range(11, len(expected) + 1))
    _, _, text = _get(base_url + "/runs/r-demo-001/events?last_event_id=r-demo-001:30")
    assert [f[2]["seq"] for f in _frames(text)] == list(range(31, len(expected) + 1))
    status, _, _ = _get(
        base_url + "/runs/r-demo-001/events", {"Last-Event-ID": f"r-demo-001:{len(expected)}"}
    )
    assert status == 204
    status, _, body = _get(base_url + "/runs/r-demo-001/events", {"Last-Event-ID": "r-other:3"})
    assert status == 400 and json.loads(body)["error"]["code"] == "invalid_last_event_id"


def test_the_refused_live_stream_ends_with_run_failed(base_url):
    _, _, text = _get(base_url + "/runs/r-demo-002/events")
    assert [f[1] for f in _frames(text)] == ["mode_notice", "run_failed"]
