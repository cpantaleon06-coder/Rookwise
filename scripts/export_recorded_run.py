"""Export a real run folder as an API v1 recording the web can replay (docs/api.md,
"Changes on 2026-10-25"; docs/api-mock.md).

Reads the three files scripts/run_incident.py writes for a run (report.json, events.json
and calls.json) and writes, into examples/api/recordings/<name>/:

- recorded_run.json: the run as a static bundle: its `RecordingSummary` (`recording`), and
  the run-scoped views `run`, `org`, `ledger`, `messages`, `tasks` and `package`.
- recorded_run.events.json: every event of the run in its original order, with its
  original id, seq, ts and payload, and the delay before it (the gap between the original
  timestamps, capped at MAX_DELAY_MS so a replay does not sit through slow calls).

What the export changes, and nothing else: `mode` becomes "recorded" in every envelope and
in `run_started` (with the `recording_id`), `run_finished.package_url` points at the
package, and `tool_called.args` is null (debug only). It never invents data: what the run
folder does not keep is left null or empty and listed under `_recording.not_filled` and in
the printed report.

Checks before anything is written: every section and event is parsed by its contract
model and validated against the committed JSON Schemas in docs/api/schemas/ (which must
match the models, as scripts/gen_api_schemas.py --check requires); money is a six-decimal
string everywhere; the output carries no secret, no prompt or model-internal field and no
hostname that the incident's synthetic corpus does not contain. The corpus is
benchmarks/incidents/<incident_id>/ by default; its logs are gitignored, so generate them
first (scripts/gen_incidents.py, or --out to a scratch directory and pass --corpus).

Usage:
    python scripts/export_recorded_run.py runs/incidents/inc-03/record --name inc-03-run2
    python scripts/export_recorded_run.py RUN_DIR --name NAME --corpus CORPUS_DIR
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))  # noqa: E402 (lets `rookwise` resolve from a checkout)

from rookwise.api import models as api  # noqa: E402
from rookwise.harness.cassette import env_secrets, find_secrets  # noqa: E402
from rookwise.money import USD_PATTERN  # noqa: E402

OUT_ROOT = REPO_ROOT / "examples" / "api" / "recordings"
CORPUS_ROOT = REPO_ROOT / "benchmarks" / "incidents"
SCHEMA_DIR = REPO_ROOT / "docs" / "api" / "schemas"
BUNDLE_FILE, EVENTS_FILE = "recorded_run.json", "recorded_run.events.json"
MAX_DELAY_MS = 1500
SECTIONS: dict[str, tuple[type, str, str | None]] = {
    # section: (model, schema file, definition inside it)
    "recording": (api.RecordingSummary, "ModesView", "RecordingSummary"),
    "run": (api.RunView, "RunView", None),
    "org": (api.OrgChart, "OrgChart", None),
    "ledger": (api.LedgerView, "LedgerView", None),
    "messages": (api.ChatMessageList, "ChatMessageList", None),
    "tasks": (api.TaskList, "TaskList", None),
    "package": (api.DeliveryPackage, "DeliveryPackage", None),
}
# Raw prompts, model internals and credentials (docs/api.md, "What the UI never receives").
FORBIDDEN = (
    '"role": "system"',
    '"role": "user"',
    '"role": "assistant"',
    '"role": "tool"',
    '"reasoning"',
    '"reasoning_content"',
    '"chat_template_kwargs"',
    '"prompt"',
    '"system_prompt"',
    "authorization",
    "bearer",
    "api_key",
    "tokenfactory",
    "nebius",
)
# A hostname ends in a public or reserved top-level label; other dotted words (file names,
# field paths such as output.claims.0.citations) are not hostnames. IPv4 addresses too.
TLDS = (
    "com net org io dev ai app co cloud info biz us uk eu de fr nl es it jp cn ru in br "
    "me tv xyz site online tech internal local localhost lan corp home test example "
    "invalid svc cluster arpa"
).split()
HOST = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:" + "|".join(TLDS) + r")\b(?![.-]\w)"
    r"|\b(?:\d{1,3}\.){3}\d{1,3}\b"
)
_USD = re.compile(USD_PATTERN)


class ExportError(Exception):
    pass


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ExportError(f"missing {path.name} in the run folder") from exc


def _dump(model: Any) -> Any:
    return model.model_dump(mode="json")


# -- building the recording -----------------------------------------------------------------


def _replay(events: list[dict[str, Any]], recording_id: str, package_url: str | None):
    """The events with mode "recorded", their original order, ids and timestamps, and the
    delay before each one (capped)."""
    if not events:
        raise ExportError("events.json has no events")
    items, previous = [], None
    for raw in events:
        event = {**raw, "mode": "recorded", "payload": dict(raw["payload"])}
        if event["type"] == "run_started":
            event["payload"].update(mode="recorded", recording_id=recording_id)
        elif event["type"] == "run_finished":
            event["payload"]["package_url"] = package_url
        elif event["type"] == "tool_called":
            event["payload"]["args"] = None
        parsed = api.SSE_EVENT_ADAPTER.validate_python(event)
        delay = 0 if previous is None else (parsed.ts - previous).total_seconds() * 1000
        if delay < 0:
            raise ExportError(f"event {parsed.id} goes back in time")
        items.append({"delay_ms": min(round(delay), MAX_DELAY_MS), "event": _dump(parsed)})
        previous = parsed.ts
    run_id = items[0]["event"]["run_id"]
    seqs = [i["event"]["seq"] for i in items]
    if seqs != list(range(1, len(items) + 1)):
        raise ExportError("event seq numbers are not 1, 2, 3, ...")
    if any(
        i["event"]["run_id"] != run_id or i["event"]["id"] != f"{run_id}:{i['event']['seq']}"
        for i in items
    ):
        raise ExportError("event ids do not all belong to one run")
    types = [i["event"]["type"] for i in items]
    if types[0] != "run_started" or types[-1] not in api.TERMINAL_EVENTS:
        raise ExportError("the run must start with run_started and end with a terminal event")
    if sum(t in api.TERMINAL_EVENTS for t in types) != 1:
        raise ExportError("the run has more than one terminal event")
    return items


def _of(items: list[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    return [i["event"] for i in items if i["event"]["type"] == event_type]


def _org(items, run_id: str, not_filled: list[str]) -> api.OrgChart:
    nodes = {
        e["payload"]["agent"]["agent_id"]: e["payload"]["agent"] for e in _of(items, "agent_hired")
    }
    status: dict[str, str] = {}
    for result in _of(items, "task_result"):
        status[result["payload"]["agent_id"]] = (
            "done" if result["payload"]["result"]["status"] == "ok" else "failed"
        )
    for stop in _of(items, "budget_exhausted"):
        status[stop["payload"]["agent_id"]] = "failed"
    if any(agent_id not in status for agent_id in nodes):
        not_filled.append(
            "org.nodes[].status of agents with no task_result or budget_exhausted (the "
            "director, managers and auditor): no event records it; kept as hired"
        )
    return api.OrgChart(
        run_id=run_id,
        mode="recorded",
        as_of_event_id=items[-1]["event"]["id"],
        nodes=[
            {**node, "status": status.get(agent_id, node["status"])}
            for agent_id, node in nodes.items()
        ],
    )


def _tasks(items, run_id: str) -> api.TaskList:
    views: dict[str, dict[str, Any]] = {}
    for assigned in _of(items, "task_assigned"):
        p = assigned["payload"]
        views[p["task"]["task_id"]] = {
            "task": p["task"],
            "agent_id": p["agent_id"],
            "operator_id": p["operator_id"],
            "status": "assigned",
            "attempts": [],
            "tool_calls": {},
        }
    for started in _of(items, "task_started"):
        if started["payload"]["task_id"] in views:
            views[started["payload"]["task_id"]]["status"] = "running"
    for recorded in _of(items, "attempt_recorded"):
        attempt = recorded["payload"]["attempt"]
        view = views.get(attempt["task_id"])
        if view is not None:
            view["attempts"].append(attempt)
            for tool, count in attempt["tool_calls"].items():
                view["tool_calls"][tool] = view["tool_calls"].get(tool, 0) + count
    for result in _of(items, "task_result"):
        view = views.get(result["payload"]["result"]["task_id"])
        if view is not None:
            ok = result["payload"]["result"]["status"] == "ok"
            view.update(
                status="ok" if ok else "failed",
                label=result["payload"]["label"],
                result=result["payload"]["result"],
            )
    return api.TaskList(run_id=run_id, mode="recorded", items=list(views.values()))


def _ledger(items, run_id: str, caps: api.RunCaps) -> api.LedgerView:
    updates = [e["payload"] for e in _of(items, "budget_update")]
    entries = [u["entry"] for u in updates if u["entry"] is not None]
    last = updates[-1] if updates else None
    zero = "0.000000"
    return api.LedgerView(
        run_id=run_id,
        mode="recorded",
        caps=caps,
        spent_usd=last["spent_usd"] if last else zero,
        held_usd=last["held_usd"] if last else zero,
        predicted_usd=last["predicted_usd"] if last else zero,
        spent_by_level=last["spent_by_level"] if last else {},
        usage_estimated_entries=sum(e["usage_estimated"] for e in entries),
        entries=entries,
        stops=[
            {
                k: e["payload"][k]
                for k in ("scope", "key", "cap_usd", "committed_usd", "requested_usd")
            }
            for e in _of(items, "budget_exhausted")
        ],
    )


def _diagnosis(report: dict[str, Any], not_filled: list[str]):
    """Diagnosis, evidence check, status and coverage from report.json. The report keeps
    claim ids and texts, the claim reasons and the withdrawn claims' citation reasons,
    not the root cause text, the citations or the remediation plan."""
    found = report.get("diagnosis") or {}
    status = None
    if found.get("status"):
        status = api.DiagnosisStatus(
            status=found["status"], reason=found.get("inconclusive_reason") or ""
        )
    diagnosis = check = None
    if found.get("category"):
        supported = found.get("supported_claims") or []
        withdrawn = found.get("withdrawn_claims") or []
        diagnosis = api.Diagnosis(
            category=found["category"],
            claims=[
                api.DiagnosisClaim(claim_id=c["claim_id"], text=c["text"])
                for c in supported + withdrawn
            ],
        )
        counts = found.get("claim_counts") or {}
        check = api.EvidenceCheck(
            claims=[
                api.ClaimCheck(claim_id=c["claim_id"], supported=True, reason="ok")
                for c in supported
            ]
            + [
                api.ClaimCheck(
                    claim_id=c["claim_id"],
                    supported=False,
                    reason=c["reason"],
                    citation_reasons=c.get("citation_reasons"),
                )
                for c in withdrawn
            ],
            supported=counts.get("supported", len(supported)),
            withdrawn=counts.get("withdrawn", len(withdrawn)),
            withdrawn_by_reason=counts.get("by_reason", {}),
        )
        not_filled += [
            "package.diagnosis.root_cause: report.json does not keep the root cause text",
            "package.diagnosis.root_cause_claim_ids: not in report.json",
            "package.diagnosis.remediation_plan: not in report.json",
            "package.diagnosis.claims[].citations (source, lines, quote): report.json keeps "
            "no citation of any claim",
            "package.evidence_check.claims[].citation_reasons of supported claims: "
            "report.json keeps citation reasons for withdrawn claims only",
            "package.diagnosis.claims order: report.json lists supported and withdrawn "
            "claims apart, so the original order across them is lost; exported supported "
            "first, then withdrawn, each in its own order",
        ]
    elif status is None:
        not_filled.append(
            "package.diagnosis, evidence_check, diagnosis_status: the run has no diagnosis"
        )
    managers = report.get("managers") or []
    coverage = api.Coverage(
        slices_read=sum(m.get("slices_read", 0) for m in managers),
        empty_slices=sum(m.get("empty_slices", 0) for m in managers),
        unread_slices=report.get("unread_slices") or [],
    )
    not_filled.append("package.coverage.empty_sources: not in report.json")
    return diagnosis, check, status, coverage


def build(
    run_dir: Path,
    *,
    recording_id: str,
    title: str,
    corpus: Path | None,
) -> tuple[dict[str, Any], dict[str, Any], list[str], list[str]]:
    """(bundle, replay, not_filled, warnings) for one run folder."""
    report = _read(run_dir / "report.json")
    events = _read(run_dir / "events.json")
    calls = _read(run_dir / "calls.json")
    not_filled: list[str] = []
    warnings: list[str] = []
    audit = report.get("audit")
    run_id = events[0]["run_id"] if events else ""
    package_url = f"/api/v1/runs/{run_id}/package" if audit else None
    items = _replay(events, recording_id, package_url)
    started = items[0]["event"]
    terminal = items[-1]["event"]
    caps = api.RunCaps(run_usd=started["payload"]["budget_usd"])
    ledger = _ledger(items, run_id, caps)
    spent = _dump(ledger)["spent_usd"]
    if spent != report.get("spent_usd") or spent != terminal["payload"]["spent_usd"]:
        raise ExportError(
            f"spent differs: ledger {spent}, report {report.get('spent_usd')}, "
            f"{terminal['type']} {terminal['payload']['spent_usd']}"
        )
    charged = [c for c in calls if "raised" not in c]
    if len(charged) != len(ledger.entries):
        warnings.append(
            f"calls.json has {len(charged)} charged calls, the events {len(ledger.entries)} "
            "ledger entries"
        )
    status = "failed" if terminal["type"] == "run_failed" else terminal["payload"]["status"]
    run = api.RunView(
        run_id=run_id,
        goal=started["payload"]["goal"],
        mode="recorded",
        recording_id=recording_id,
        simulated_case=started["payload"]["simulated_case"],
        status=status,
        board=started["payload"]["board"],
        caps=caps,
        spent_usd=ledger.spent_usd,
        held_usd=ledger.held_usd,
        predicted_usd=ledger.predicted_usd,
        created_at=started["ts"],
        finished_at=terminal["ts"],
        events_url=f"/api/v1/runs/{run_id}/events",
    )
    messages = api.ChatMessageList(
        run_id=run_id,
        mode="recorded",
        items=[e["payload"]["message"] for e in _of(items, "message")],
    )
    tasks = _tasks(items, run_id)
    category = None
    incident_id = report.get("incident_id")
    truth = corpus / "ground_truth.json" if corpus else None
    if truth is not None and truth.exists():
        category = json.loads(truth.read_text(encoding="utf-8")).get("root_cause_category")
    else:
        not_filled.append("recording.category: no ground_truth.json in the corpus folder")
    recording = api.RecordingSummary(
        recording_id=recording_id,
        title=title,
        goal=run.goal,
        simulated_case=run.simulated_case,
        spent_usd=run.spent_usd,
        recorded_at=run.created_at,
        incident_id=incident_id,
        category=category,
    )
    package = None
    if audit:
        diagnosis, check, diagnosis_status, coverage = _diagnosis(report, not_filled)
        director = [m.text for m in messages.items if m.sender == "director"]
        package = api.DeliveryPackage(
            run_id=run_id,
            mode="recorded",
            simulated_case=run.simulated_case,
            summary=director[-1] if director else "",
            deliverables=[],
            cost_report=api.CostReport(
                predicted_usd=ledger.predicted_usd,
                real_usd=ledger.spent_usd,
                prediction_error=report.get("prediction_error"),
                spent_by_level=ledger.spent_by_level,
                usage_estimated_entries=ledger.usage_estimated_entries,
            ),
            contracts=[
                api.ContractRecord(task=view.task, result=view.result) for view in tasks.items
            ],
            decisions=list(report.get("notes") or []),
            audit=audit,
            diagnosis=diagnosis,
            evidence_check=check,
            diagnosis_status=diagnosis_status,
            coverage=coverage,
        )
        not_filled.append(
            "package.deliverables: the run's store:// outputs are not in the run folder; "
            "sent empty (package.summary is the director's last message)"
        )
    else:
        not_filled.append("package: the run has no audit verdict, so no package (409)")
    not_filled.append(
        "events: no mode_notice (recorded_mode) at the start, as docs/api.md asks of a "
        "recorded stream: the run did not emit one and adding it would change the "
        "original ids"
    )
    bundle_sections = {
        "recording": _dump(recording),
        "run": _dump(run),
        "org": _dump(_org(items, run_id, not_filled)),
        "ledger": _dump(ledger),
        "messages": _dump(messages),
        "tasks": _dump(tasks),
        "package": _dump(package) if package else None,
    }
    header = {
        "real_model_output": True,
        "synthetic_corpus": bool(run.simulated_case),
        "api_version": api.API_VERSION,
        "incident_id": incident_id,
        "run_folder": "/".join(run_dir.resolve().parts[-2:]),
        "exported_by": "scripts/export_recorded_run.py",
        "max_delay_ms": MAX_DELAY_MS,
        "changes": [
            'mode is "recorded" in every envelope and in run_started (with recording_id)',
            "run_finished.package_url points at the package" if package else "",
            "tool_called.args is null",
        ],
        "not_filled": not_filled,
        "note": (
            "A REAL run of the Rookwise team on a SYNTHETIC incident: texts are model "
            "output about fictional logs. Exported from its run folder; nothing was added."
        ),
    }
    header["changes"] = [c for c in header["changes"] if c]
    bundle = {"_recording": header, **bundle_sections}
    replay = {"_recording": header, "run_id": run_id, "events": items}
    return bundle, replay, not_filled, warnings


# -- checks ---------------------------------------------------------------------------------


def _schemas() -> dict[str, dict[str, Any]]:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import gen_api_schemas  # noqa: PLC0415 (a sibling script, not a package)

    wanted = gen_api_schemas.schemas()
    out = {}
    for name, text in wanted.items():
        path = SCHEMA_DIR / name
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            raise ExportError(f"docs/api/schemas/{name} is stale: run gen_api_schemas.py")
        out[name.removesuffix(".json")] = json.loads(text)
    return out


_IGNORED = {"title", "description", "default", "$id", "$schema", "$defs", "discriminator"}


def check_schema(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str = "$"):
    """Validates `value` against a JSON Schema using only the keywords the generated
    schemas use; any other keyword is an error, so nothing passes unchecked."""
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            raise ExportError(f"{path}: unsupported $ref {ref}")
        check_schema(value, root["$defs"][ref.removeprefix("#/$defs/")], root, path)
    for key in set(schema) - _IGNORED - {"$ref"}:
        rule = schema[key]
        if key == "type":
            kinds = rule if isinstance(rule, list) else [rule]
            if not any(_is_type(value, kind) for kind in kinds):
                raise ExportError(f"{path}: expected {rule}, got {type(value).__name__}")
        elif key == "enum":
            if value not in rule:
                raise ExportError(f"{path}: {value!r} not in {rule}")
        elif key == "const":
            if value != rule:
                raise ExportError(f"{path}: {value!r} is not {rule!r}")
        elif key in ("anyOf", "oneOf"):
            passed = 0
            for option in rule:
                try:
                    check_schema(value, option, root, path)
                    passed += 1
                except ExportError:
                    pass
            if passed == 0 or (key == "oneOf" and passed != 1):
                raise ExportError(f"{path}: matches {passed} of the {key} options")
        elif key in ("properties", "required", "additionalProperties", "propertyNames"):
            if isinstance(value, dict):
                _check_object(value, schema, root, path, key)
        elif key == "items":
            if isinstance(value, list):
                for index, item in enumerate(value):
                    check_schema(item, rule, root, f"{path}[{index}]")
        elif key in ("pattern", "format", "minLength", "maxLength"):
            if isinstance(value, str):
                _check_string(value, key, rule, path)
        elif key == "minimum":
            if _is_type(value, "number") and value < rule:
                raise ExportError(f"{path}: {value} is below {rule}")
        else:
            raise ExportError(f"{path}: schema keyword {key!r} is not supported")


def _is_type(value: Any, kind: str) -> bool:
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    expected = {"object": dict, "array": list, "string": str, "boolean": bool}.get(kind)
    if kind == "null":
        return value is None
    if expected is None:
        raise ExportError(f"unsupported schema type {kind!r}")
    return isinstance(value, expected)


def _check_object(value, schema, root, path, key) -> None:
    properties = schema.get("properties", {})
    if key == "required":
        missing = [name for name in schema["required"] if name not in value]
        if missing:
            raise ExportError(f"{path}: missing {missing}")
    elif key == "properties":
        for name, sub in properties.items():
            if name in value:
                check_schema(value[name], sub, root, f"{path}.{name}")
    elif key == "additionalProperties":
        extra = schema["additionalProperties"]
        for name, item in value.items():
            if name in properties:
                continue
            if extra is False:
                raise ExportError(f"{path}: unknown field {name!r}")
            if isinstance(extra, dict):
                check_schema(item, extra, root, f"{path}.{name}")
    elif key == "propertyNames":
        for name in value:
            check_schema(name, schema["propertyNames"], root, f"{path}.<key {name}>")


def _check_string(value: str, key: str, rule: Any, path: str) -> None:
    if key == "pattern" and not re.search(rule, value):
        raise ExportError(f"{path}: {value!r} does not match {rule}")
    if key == "minLength" and len(value) < rule:
        raise ExportError(f"{path}: shorter than {rule}")
    if key == "maxLength" and len(value) > rule:
        raise ExportError(f"{path}: longer than {rule}")
    if key == "format":
        if rule != "date-time":
            raise ExportError(f"{path}: format {rule!r} is not supported")
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ExportError(f"{path}: {value!r} is not a date-time") from exc


def validate(bundle: dict[str, Any], replay: dict[str, Any]) -> None:
    """Each section and event through its contract model (from its JSON text) and against
    the committed schemas; money must be a six-decimal string everywhere."""
    schemas = _schemas()
    for section, (model, schema_name, definition) in SECTIONS.items():
        value = bundle[section]
        if value is None:
            continue
        model.model_validate_json(json.dumps(value))
        root = schemas[schema_name]
        schema = {"$ref": f"#/$defs/{definition}"} if definition else root
        check_schema(value, schema, root, section)
    event_schema = schemas["SseEvent"]
    for item in replay["events"]:
        api.SSE_EVENT_ADAPTER.validate_json(json.dumps(item["event"]))
        check_schema(item["event"], event_schema, event_schema, f"event {item['event']['id']}")
        if not isinstance(item["delay_ms"], int) or not 0 <= item["delay_ms"] <= MAX_DELAY_MS:
            raise ExportError(f"event {item['event']['id']}: delay_ms out of range")
    for where, value in _walk({"bundle": bundle, "replay": replay}):
        key = where.rsplit(".", 1)[-1]
        if _is_money_key(key) and not (isinstance(value, str) and _USD.match(value)):
            raise ExportError(f"{where}: money must be a six-decimal string, got {value!r}")


def _is_money_key(key: str) -> bool:
    key = key.split("[", 1)[0]
    return key == "usd" or key.startswith("usd_") or key.endswith("_usd") or "_usd_" in key


def _walk(value: Any, path: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "_recording":
                continue
            if key in ("spent_by_level", "level_usd") and isinstance(item, dict):
                for level, usd in item.items():
                    yield f"{path}.{key}.{level}_usd", usd
                continue
            yield from _walk(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")
    else:
        yield path, value


def corpus_hosts(corpus: Path) -> set[str]:
    """Hostnames and IPv4 addresses found in the corpus files."""
    hosts: set[str] = set()
    for path in corpus.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            hosts.update(HOST.findall(text))
    return hosts


def check_content(texts: list[str], data: str, corpus: Path | None) -> list[str]:
    """Problems in the output: secrets and prompt or model-internal fields in any file
    text, and hostnames in the run's data (`data`, the output without the export's own
    `_recording` header) that the incident's synthetic corpus does not contain."""
    problems: list[str] = []
    for text in texts:
        problems += find_secrets(text, env_secrets())
        lowered = text.lower()
        problems += [f"forbidden text {f!r}" for f in FORBIDDEN if f in lowered]
    allowed = corpus_hosts(corpus) if corpus is not None and corpus.is_dir() else set()
    unknown = sorted(set(HOST.findall(data.lower())) - allowed)
    problems += [f"hostname {h!r} is not in the corpus" for h in unknown]
    return sorted(set(problems))


# -- main -----------------------------------------------------------------------------------


def export(
    run_dir: Path,
    name: str,
    *,
    out_root: Path = OUT_ROOT,
    corpus: Path | None = None,
    recording_id: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Writes the recording and returns the report (also printed by main)."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
        raise ExportError("--name must be lowercase letters, digits and dashes")
    report = _read(run_dir / "report.json")
    incident_id = report.get("incident_id")
    if corpus is None and incident_id:
        corpus = CORPUS_ROOT / incident_id
    recording_id = recording_id or f"rec-{name}"
    title = title or f"Incident {incident_id}, recorded run ({name})"
    bundle, replay, not_filled, warnings = build(
        run_dir, recording_id=recording_id, title=title, corpus=corpus
    )
    validate(bundle, replay)
    texts = {
        BUNDLE_FILE: json.dumps(bundle, indent=2, ensure_ascii=False) + "\n",
        EVENTS_FILE: json.dumps(replay, indent=2, ensure_ascii=False) + "\n",
    }
    data = json.dumps(
        [{k: v for k, v in bundle.items() if k != "_recording"}, replay["events"]],
        ensure_ascii=False,
    )
    problems = check_content(list(texts.values()), data, corpus)
    if problems:
        raise ExportError("refusing to write: " + "; ".join(problems))
    out_dir = out_root / name
    out_dir.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for file_name, text in texts.items():
        (out_dir / file_name).write_text(text, encoding="utf-8")
        sizes[file_name] = (out_dir / file_name).stat().st_size
    return {
        "out_dir": str(out_dir),
        "recording_id": recording_id,
        "run_id": bundle["run"]["run_id"],
        "incident_id": incident_id,
        "status": bundle["run"]["status"],
        "spent_usd": bundle["run"]["spent_usd"],
        "events": len(replay["events"]),
        "replay_s": sum(i["delay_ms"] for i in replay["events"]) / 1000,
        "bytes": sizes,
        "not_filled": not_filled,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("run_dir", type=Path, help="folder with report/events/calls.json")
    parser.add_argument("--name", required=True, help="output folder under --out-root")
    parser.add_argument("--out-root", type=Path, default=OUT_ROOT)
    parser.add_argument("--corpus", type=Path, help="the incident's corpus folder")
    parser.add_argument("--recording-id")
    parser.add_argument("--title")
    args = parser.parse_args()
    try:
        result = export(
            args.run_dir,
            args.name,
            out_root=args.out_root,
            corpus=args.corpus,
            recording_id=args.recording_id,
            title=args.title,
        )
    except ExportError as exc:
        print(f"export failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
