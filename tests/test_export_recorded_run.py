"""scripts/export_recorded_run.py on a small SYNTHETIC run folder built from the synthetic
API fixture's events (mode set back to live, as scripts/run_incident.py writes them)."""

from __future__ import annotations

import copy
import importlib.util
import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from rookwise.api import SCHEMA_MODELS, SSE_EVENT_ADAPTER
from rookwise.money import USD_PATTERN

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "examples" / "api"


def _script():
    path = ROOT / "scripts" / "export_recorded_run.py"
    spec = importlib.util.spec_from_file_location("export_recorded_run", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


exporter = _script()


def _live_events() -> list[dict]:
    replay = json.loads((FIXTURES / "recorded_run.events.json").read_text(encoding="utf-8"))
    events = []
    for item in replay["events"]:
        event = copy.deepcopy(item["event"])
        if event["type"] == "mode_notice":  # a live run has no recorded_mode notice
            continue
        event["mode"] = "live"
        if event["type"] == "run_started":
            event["payload"].update(mode="live", recording_id=None)
        if event["type"] == "run_finished":
            event["payload"]["package_url"] = None
        if event["type"] == "tool_called":
            event["payload"]["args"] = {"query": "[synthetic] bakery hours"}
        events.append(event)
    for seq, event in enumerate(events, 1):  # renumber after dropping the notice
        event["seq"], event["id"] = seq, f"{event['run_id']}:{seq}"
    return events


def _report(events: list[dict]) -> dict:
    finished = events[-1]["payload"]
    audit = next(e for e in events if e["type"] == "audit_result")["payload"]["audit"]
    return {
        "incident_id": "inc-syn",
        "status": "finished",
        "partial": True,
        "notes": ["[synthetic] t-3: operator failed (top_of_ladder); the manager reassigns."],
        "spent_usd": finished["spent_usd"],
        "predicted_usd": finished["predicted_usd"],
        "prediction_error": 0.1,
        "unread_slices": [{"source_id": "logs/app.log", "line_start": 401, "line_end": 800}],
        "managers": [
            {"block_id": "b-1", "slices_read": 3, "empty_slices": 1},
            {"block_id": "b-2", "slices_read": 2, "empty_slices": 0},
        ],
        "diagnosis": {
            "status": "audited",
            "inconclusive_reason": "",
            "category": "capacity_exhaustion",
            "supported_claims": [
                {"claim_id": "c1", "text": "[synthetic] The pool on pay-gw.example.net filled."},
                {"claim_id": "c3", "text": "[synthetic] Requests queued after 02:10."},
            ],
            "withdrawn_claims": [
                {
                    "claim_id": "c2",
                    "text": "[synthetic] The deploy changed the pool size.",
                    "reason": "quote_not_found",
                    "citation_reasons": ["ok", "quote_not_found"],
                }
            ],
            "claim_counts": {
                "supported": 2,
                "withdrawn": 1,
                "by_reason": {"quote_not_found": 1},
            },
        },
        "audit": audit,
    }


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    events = _live_events()
    entries = [e for e in events if e["type"] == "budget_update" and e["payload"]["entry"]]
    calls = [{"level": e["payload"]["entry"]["level"], "usd": "0.000001"} for e in entries]
    folder = tmp_path / "runs" / "inc-syn" / "record"
    folder.mkdir(parents=True)
    for name, data in (("events", events), ("report", _report(events)), ("calls", calls)):
        (folder / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    return folder


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    folder = tmp_path / "corpus" / "inc-syn"
    (folder / "logs").mkdir(parents=True)
    (folder / "ground_truth.json").write_text(
        json.dumps({"synthetic": True, "root_cause_category": "capacity_exhaustion"}),
        encoding="utf-8",
    )
    (folder / "logs" / "app.log").write_text(
        "SYNTHETIC\n2026-05-20T02:10:00Z WARN pool full host=pay-gw.example.net\n",
        encoding="utf-8",
    )
    return folder


def _export(run_dir: Path, corpus: Path, tmp_path: Path):
    result = exporter.export(run_dir, "inc-syn-run1", out_root=tmp_path / "out", corpus=corpus)
    out = tmp_path / "out" / "inc-syn-run1"
    bundle = json.loads((out / exporter.BUNDLE_FILE).read_text(encoding="utf-8"))
    replay = json.loads((out / exporter.EVENTS_FILE).read_text(encoding="utf-8"))
    return result, bundle, replay


def test_the_export_keeps_order_ids_and_payloads_and_labels_it_recorded(run_dir, corpus, tmp_path):
    original = json.loads((run_dir / "events.json").read_text(encoding="utf-8"))
    _, bundle, replay = _export(run_dir, corpus, tmp_path)
    events = [item["event"] for item in replay["events"]]
    assert [e["id"] for e in events] == [e["id"] for e in original]
    assert [e["type"] for e in events] == [e["type"] for e in original]
    assert {e["mode"] for e in events} == {"recorded"}
    started = events[0]["payload"]
    assert (started["mode"], started["recording_id"]) == ("recorded", "rec-inc-syn-run1")
    assert events[-1]["payload"]["package_url"] == "/api/v1/runs/run_8f2c1a7d4b/package"
    assert all(e["payload"]["args"] is None for e in events if e["type"] == "tool_called")
    for before, after in zip(original, events, strict=True):
        if before["type"] not in ("run_started", "run_finished", "tool_called"):
            assert (
                after["payload"]
                == SSE_EVENT_ADAPTER.validate_python(before).model_dump(mode="json")["payload"]
            )
    for section in ("run", "org", "ledger", "messages", "tasks", "package"):
        assert bundle[section]["mode"] == "recorded", section
    assert bundle["_recording"]["real_model_output"] is True


def test_delays_follow_the_timestamps_and_are_capped(run_dir, corpus, tmp_path):
    original = json.loads((run_dir / "events.json").read_text(encoding="utf-8"))
    original[5]["ts"] = "2026-10-20T15:09:00Z"  # a slow call: minutes between two events
    for event in original[6:]:
        event["ts"] = "2026-10-20T15:09:01Z"
    (run_dir / "events.json").write_text(json.dumps(original), encoding="utf-8")
    _, _, replay = _export(run_dir, corpus, tmp_path)
    delays = [item["delay_ms"] for item in replay["events"]]
    assert delays[0] == 0 and delays[5] == exporter.MAX_DELAY_MS == 1500
    assert delays[6] == 1000 and all(d == 0 for d in delays[7:])
    ts = [datetime.fromisoformat(i["event"]["ts"]) for i in replay["events"]]
    assert ts == sorted(ts)
    gaps = [(b - a).total_seconds() * 1000 for a, b in zip(ts, ts[1:], strict=False)]
    assert delays[1:] == [min(round(g), 1500) for g in gaps]


def test_the_bundle_validates_and_money_stays_a_string(run_dir, corpus, tmp_path):
    _, bundle, replay = _export(run_dir, corpus, tmp_path)
    for section, (model, _, _) in exporter.SECTIONS.items():
        model.model_validate(bundle[section])
    exporter.validate(bundle, replay)
    run, ledger = bundle["run"], bundle["ledger"]
    assert run["spent_usd"] == ledger["spent_usd"] == bundle["package"]["cost_report"]["real_usd"]
    assert run["status"] == "finished" and run["caps"]["run_usd"] == "0.250000"
    for path, value in exporter._walk({"bundle": bundle, "replay": replay}):
        if exporter._is_money_key(path.rsplit(".", 1)[-1]):
            assert isinstance(value, str) and re.match(USD_PATTERN, value), path
    tasks = {t["task"]["task_id"]: t for t in bundle["tasks"]["items"]}
    assert tasks["t-1"]["status"] == "ok" and tasks["t-1"]["tool_calls"] == {"search": 1}
    assert tasks["t-3"]["label"] == "failed"
    nodes = {n["agent_id"]: n["status"] for n in bundle["org"]["nodes"]}
    assert nodes["a-op-research"] == "done" and nodes["a-op-menu-2"] == "failed"
    assert nodes["a-director"] == "hired"  # no event says otherwise; not invented


def test_the_package_carries_what_the_report_has_and_lists_the_rest(run_dir, corpus, tmp_path):
    result, bundle, _ = _export(run_dir, corpus, tmp_path)
    package = SCHEMA_MODELS["DeliveryPackage"].model_validate(bundle["package"])
    assert [c.claim_id for c in package.diagnosis.claims] == ["c1", "c3", "c2"]
    assert package.diagnosis.root_cause is None and package.diagnosis.remediation_plan is None
    assert all(c.citations is None for c in package.diagnosis.claims)
    checks = {c.claim_id: c for c in package.evidence_check.claims}
    assert checks["c1"].supported and checks["c1"].citation_reasons is None
    assert checks["c2"].citation_reasons == ["ok", "quote_not_found"]
    assert (package.evidence_check.supported, package.evidence_check.withdrawn) == (2, 1)
    assert package.diagnosis_status.status == "audited"
    assert (package.coverage.slices_read, package.coverage.empty_slices) == (5, 1)
    assert package.coverage.unread_slices[0].line_start == 401
    assert package.coverage.empty_sources is None
    assert package.deliverables == [] and package.decisions[0].startswith("[synthetic]")
    recording = bundle["recording"]
    assert (recording["incident_id"], recording["category"]) == ("inc-syn", "capacity_exhaustion")
    assert recording["recorded_at"] == bundle["run"]["created_at"]
    gaps = " ".join(result["not_filled"])
    for missing in ("root_cause", "remediation_plan", "citations", "empty_sources", "mode_notice"):
        assert missing in gaps, missing
    assert result["not_filled"] == bundle["_recording"]["not_filled"]


def test_a_run_without_an_audit_has_no_package(run_dir, corpus, tmp_path):
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    report["audit"] = None
    (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    result, bundle, replay = _export(run_dir, corpus, tmp_path)
    assert bundle["package"] is None
    assert replay["events"][-1]["event"]["payload"]["package_url"] is None
    assert any(n.startswith("package:") for n in result["not_filled"])


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("[synthetic] see metrics.acme-internal.io", "hostname 'metrics.acme-internal.io'"),
        ("[synthetic] host 203.0.113.99 answered", "hostname '203.0.113.99'"),
        ("[synthetic] Authorization: Bearer abcdefghijklmnop", "bearer"),
        # Built at runtime so this file does not itself match the release key-pattern check.
        ("[synthetic] token " + "sk" + "-abcdefghijklmnopqrstu", "sk-"),
    ],
)
def test_it_refuses_unknown_hostnames_and_secrets(run_dir, corpus, tmp_path, text, problem):
    events = json.loads((run_dir / "events.json").read_text(encoding="utf-8"))
    message = next(e for e in events if e["type"] == "message")
    message["payload"]["message"]["text"] = text
    (run_dir / "events.json").write_text(json.dumps(events), encoding="utf-8")
    with pytest.raises(exporter.ExportError, match="refusing to write") as caught:
        exporter.export(run_dir, "inc-syn-run1", out_root=tmp_path / "out", corpus=corpus)
    assert problem in str(caught.value).lower()
    assert not (tmp_path / "out" / "inc-syn-run1").exists()


def test_it_refuses_a_spend_that_does_not_add_up(run_dir, corpus, tmp_path):
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    report["spent_usd"] = "0.999999"
    (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(exporter.ExportError, match="spent differs"):
        exporter.export(run_dir, "inc-syn-run1", out_root=tmp_path / "out", corpus=corpus)


def test_the_schema_check_refuses_what_the_schemas_refuse():
    schemas = exporter._schemas()
    run = json.loads((FIXTURES / "recorded_run.json").read_text(encoding="utf-8"))["run"]
    root = schemas["RunView"]
    exporter.check_schema(run, root, root)
    for broken, match in (
        ({**run, "extra": 1}, "unknown field"),
        ({**run, "spent_usd": 0.0159}, "expected"),
        ({**run, "spent_usd": "0.0159"}, "does not match"),
        ({**run, "status": "done"}, "not in"),
        ({k: v for k, v in run.items() if k != "goal"}, "missing"),
        ({**run, "created_at": "yesterday"}, "date-time"),
    ):
        with pytest.raises(exporter.ExportError, match=match):
            exporter.check_schema(broken, root, root)
    with pytest.raises(exporter.ExportError, match="not supported"):
        exporter.check_schema(1, {"multipleOf": 2}, {})


def _sidecar(run_id: str = "run_8f2c1a7d4b") -> dict:
    def cite(line: int, quote: str) -> dict:
        return {"source_id": "logs/app.log", "line_start": line, "line_end": line, "quote": quote}

    return {
        "_recovered": {
            "version": 1,
            "tool": "tools/recover_diagnosis.py",
            "incident_id": "inc-syn",
            "run_id": run_id,
            "commit": "abc1234",
            "cassette": "inc-syn.run1.json",
            "verified": {"events": 63, "report_keys": [], "against": "inc-syn/record"},
        },
        "diagnosis": {
            "root_cause": "[synthetic] The pool on pay-gw.example.net filled at 02:10.",
            "category": "capacity_exhaustion",
            "claims": [
                {
                    "claim_id": "c1",
                    "text": "[synthetic] The pool on pay-gw.example.net filled.",
                    "citations": [cite(2, "WARN pool full host=pay-gw.example.net")],
                },
                {
                    "claim_id": "c2",
                    "text": "[synthetic] The deploy changed the pool size.",
                    "citations": [cite(2, "pool full"), cite(2, "pool size=4")],
                },
                {
                    "claim_id": "c3",
                    "text": "[synthetic] Requests queued after 02:10.",
                    "citations": [cite(2, "02:10:00Z")],
                },
            ],
            "root_cause_claim_ids": ["c1", "c3"],
            "remediation_plan": [
                {
                    "action": "[synthetic] Raise the pool size.",
                    "why": "[synthetic] The pool filled.",
                    "risk": "[synthetic] More memory.",
                    "reversible": True,
                }
            ],
        },
        "evidence": [
            {"claim_id": "c1", "supported": True, "reason": "ok", "citation_reasons": ["ok"]},
            {
                "claim_id": "c2",
                "supported": False,
                "reason": "quote_not_found",
                "citation_reasons": ["ok", "quote_not_found"],
            },
            {"claim_id": "c3", "supported": True, "reason": "ok", "citation_reasons": ["ok"]},
        ],
        "empty_sources": ["logs/empty.log"],
    }


def _export_with(run_dir, corpus, tmp_path, sidecar):
    path = tmp_path / "diagnosis.json"
    path.write_text(json.dumps(sidecar), encoding="utf-8")
    return exporter.export(
        run_dir, "inc-syn-run1", out_root=tmp_path / "out", corpus=corpus, diagnosis=path
    )


def test_a_recovered_diagnosis_fills_the_gaps_in_the_original_order(run_dir, corpus, tmp_path):
    result = _export_with(run_dir, corpus, tmp_path, _sidecar())
    out = tmp_path / "out" / "inc-syn-run1"
    bundle = json.loads((out / exporter.BUNDLE_FILE).read_text(encoding="utf-8"))
    package = SCHEMA_MODELS["DeliveryPackage"].model_validate(bundle["package"])
    assert [c.claim_id for c in package.diagnosis.claims] == ["c1", "c2", "c3"]
    assert package.diagnosis.root_cause.startswith("[synthetic] The pool")
    assert package.diagnosis.root_cause_claim_ids == ["c1", "c3"]
    assert package.diagnosis.remediation_plan[0].action == "[synthetic] Raise the pool size."
    assert [len(c.citations) for c in package.diagnosis.claims] == [1, 2, 1]
    assert [c.citation_reasons for c in package.evidence_check.claims] == [
        ["ok"],
        ["ok", "quote_not_found"],
        ["ok"],
    ]
    assert (package.evidence_check.supported, package.evidence_check.withdrawn) == (2, 1)
    assert package.coverage.empty_sources == ["logs/empty.log"]
    gaps = " ".join(result["not_filled"])
    for filled in ("root_cause", "remediation_plan", "citations", "empty_sources", "order"):
        assert filled not in gaps, filled
    assert "mode_notice" in gaps  # still not in the run, still listed
    source = bundle["_recording"]["diagnosis_source"]
    assert (source["tool"], source["commit"]) == ("tools/recover_diagnosis.py", "abc1234")


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda s: s["_recovered"].update(run_id="run_other"), "for another run"),
        (lambda s: s["diagnosis"]["claims"][0].update(text="[synthetic] x"), "text differs"),
        (lambda s: s["evidence"][1].update(citation_reasons=["ok", "ok"]), "reasons differ"),
        (lambda s: s["evidence"][0].update(supported=False), "differ from report"),
        (lambda s: s["diagnosis"]["root_cause_claim_ids"].append("c9"), "unknown claims"),
        (
            lambda s: s["diagnosis"]["claims"][2]["citations"].append(
                s["diagnosis"]["claims"][2]["citations"][0]
            ),
            "citation count",
        ),
    ],
)
def test_a_sidecar_from_another_run_is_refused(run_dir, corpus, tmp_path, change, match):
    sidecar = _sidecar()
    change(sidecar)
    with pytest.raises(exporter.ExportError, match=match):
        _export_with(run_dir, corpus, tmp_path, sidecar)
    assert not (tmp_path / "out" / "inc-syn-run1").exists()
