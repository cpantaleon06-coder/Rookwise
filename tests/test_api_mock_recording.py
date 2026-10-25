"""The API v1 mock with exported recordings (--recording): listed in GET /modes and
GET /runs, served by run id, streamed as SSE. The recordings are exported by
scripts/export_recorded_run.py from small SYNTHETIC run folders. No outside network."""

import importlib.util
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from rookwise.api import SCHEMA_MODELS

ROOT = Path(__file__).resolve().parents[1]


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


serve = _module("rookwise_api_mock_rec", ROOT / "examples" / "api" / "mock" / "serve.py")
export_tests = _module("export_tests", ROOT / "tests" / "test_export_recorded_run.py")
exporter = export_tests.exporter

RUN_A, RUN_B = "run_5c0ffee0a1", "run_5c0ffee0b2"


def _recording(tmp: Path, run_id: str, name: str, *, day: str, audit: bool) -> Path:
    text = json.dumps(export_tests._live_events())
    text = text.replace("run_8f2c1a7d4b", run_id).replace("2026-10-20T", f"2026-10-{day}T")
    events = json.loads(text)
    report = export_tests._report(events)
    if not audit:
        report["audit"] = None
    folder = tmp / "runs" / name
    folder.mkdir(parents=True)
    (folder / "events.json").write_text(json.dumps(events), encoding="utf-8")
    (folder / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (folder / "calls.json").write_text("[]", encoding="utf-8")
    corpus = tmp / "corpus" / name
    (corpus / "logs").mkdir(parents=True)
    (corpus / "ground_truth.json").write_text(
        json.dumps({"root_cause_category": "capacity_exhaustion"}), encoding="utf-8"
    )
    (corpus / "logs" / "app.log").write_text("host=pay-gw.example.net\n", encoding="utf-8")
    exporter.export(folder, name, out_root=tmp / "out", corpus=corpus)
    return tmp / "out" / name


@pytest.fixture(scope="module")
def recordings(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("mock-recordings")
    return (
        _recording(tmp, RUN_A, "syn-a", day="24", audit=True),
        _recording(tmp, RUN_B, "syn-b", day="22", audit=False),
    )


@pytest.fixture(scope="module")
def base_url(recordings):
    server = serve.make_server(port=0, speed=0, recordings=recordings)
    server.RequestHandlerClass.log_message = lambda *a: None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/api/v1"
    server.shutdown()
    server.server_close()


def _call(url, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="GET" if body is None else "POST", headers=headers or {}
    )
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


def test_modes_list_the_recordings_first(base_url):
    status, text = _call(f"{base_url}/modes")
    modes = SCHEMA_MODELS["ModesView"].model_validate_json(text)
    assert status == 200
    ids = [r.recording_id for r in modes.recordings]
    assert ids == ["rec-syn-a", "rec-syn-b", "rec-demo-bakery-001"]
    first = modes.recordings[0]
    assert (first.incident_id, first.category) == ("inc-syn", "capacity_exhaustion")
    assert first.recorded_at.isoformat().startswith("2026-10-24T15:00:00")


def test_runs_list_every_recorded_run_newest_first(base_url):
    status, text = _call(f"{base_url}/runs")
    runs = SCHEMA_MODELS["RunList"].model_validate_json(text)
    assert status == 200
    assert [r.run_id for r in runs.items] == [RUN_A, RUN_B, "run_8f2c1a7d4b"]
    assert {r.mode for r in runs.items} == {"recorded"}


def test_run_views_come_from_the_recording(base_url):
    for path, schema in (
        ("", "RunView"),
        ("/org", "OrgChart"),
        ("/ledger", "LedgerView"),
        ("/tasks", "TaskList"),
        ("/messages", "ChatMessageList"),
        ("/package", "DeliveryPackage"),
    ):
        status, text = _call(f"{base_url}/runs/{RUN_A}{path}")
        assert status == 200, path
        view = SCHEMA_MODELS[schema].model_validate_json(text)
        assert view.run_id == RUN_A and view.mode == "recorded"
    package = SCHEMA_MODELS["DeliveryPackage"].model_validate_json(
        _call(f"{base_url}/runs/{RUN_A}/package")[1]
    )
    assert package.diagnosis.category == "capacity_exhaustion"
    assert package.evidence_check.withdrawn == 1


def test_a_recording_without_a_package_answers_409(base_url):
    status, text = _call(f"{base_url}/runs/{RUN_B}/package")
    assert status == 409 and json.loads(text)["error"]["code"] == "package_not_ready"
    assert _call(f"{base_url}/runs/{RUN_B}")[0] == 200


def test_post_runs_starts_the_chosen_recording_and_it_cannot_change(base_url):
    status, text = _call(f"{base_url}/runs", {"mode": "recorded", "recording_id": "rec-syn-a"})
    assert status == 201 and json.loads(text)["run_id"] == RUN_A
    status, text = _call(f"{base_url}/runs", {"mode": "recorded", "recording_id": "rec-x"})
    assert status == 422
    for action in ("messages", "approval", "cancel"):
        status, text = _call(f"{base_url}/runs/{RUN_A}/{action}", {"text": "hi"})
        assert status == 409 and json.loads(text)["error"]["code"] == "recorded_run", action


def test_the_stream_replays_the_exported_events_and_resumes(base_url, recordings):
    replay = json.loads((recordings[0] / exporter.EVENTS_FILE).read_text(encoding="utf-8"))
    expected = [item["event"] for item in replay["events"]]
    status, text = _call(f"{base_url}/runs/{RUN_A}/events")
    sent = [json.loads(line[6:]) for line in text.split("\n") if line.startswith("data: ")]
    assert status == 200 and sent == expected
    status, text = _call(
        f"{base_url}/runs/{RUN_A}/events", headers={"Last-Event-ID": f"{RUN_A}:10"}
    )
    resumed = [json.loads(line[6:]) for line in text.split("\n") if line.startswith("data: ")]
    assert [e["seq"] for e in resumed] == list(range(11, len(expected) + 1))


def test_bad_recording_folders_are_refused(recordings, tmp_path):
    with pytest.raises(ValueError, match="already served"):
        serve.Fixtures([recordings[0], recordings[0]])
    (tmp_path / "recorded_run.json").write_text(json.dumps({"run": {}}), encoding="utf-8")
    (tmp_path / "recorded_run.events.json").write_text('{"events": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="not an exported recording"):
        serve.Fixtures([tmp_path])


def test_without_recordings_the_mock_serves_the_fixtures_only():
    fixtures = serve.Fixtures()
    assert [r["recording_id"] for r in fixtures.modes["recordings"]] == ["rec-demo-bakery-001"]
    assert fixtures.modes == fixtures.bundle["modes"]
    assert fixtures.run_list == fixtures.bundle["runs"]
