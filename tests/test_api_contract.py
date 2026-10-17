"""API v1 contract: committed schemas match the models, and every fixture validates.

The fixtures are validated with the pydantic models the JSON Schemas are generated
from; a drift test keeps the committed schemas identical to the models, so the two
checks together amount to validating against the schemas. No network.
"""

import importlib.util
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from rookwise.api import EVENT_TYPES, SCHEMA_MODELS, SSE_EVENT_ADAPTER, TERMINAL_EVENTS
from rookwise.api.models import CreateRunRequest
from rookwise.harness.cassette import env_secrets, find_secrets
from rookwise.money import USD_PATTERN, ZERO_USD

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "docs" / "api" / "schemas"
FIXTURES = ROOT / "examples" / "api"
BUNDLE_SECTIONS = {
    "modes": "ModesView",
    "run": "RunView",
    "runs": "RunList",
    "org": "OrgChart",
    "ledger": "LedgerView",
    "messages": "ChatMessageList",
    "tasks": "TaskList",
    "package": "DeliveryPackage",
}


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_committed_schemas_match_the_models():
    wanted = _script("gen_api_schemas").schemas()
    on_disk = {p.name: p.read_text(encoding="utf-8") for p in SCHEMA_DIR.glob("*.json")}
    assert sorted(on_disk) == sorted(wanted)
    for name, text in wanted.items():
        assert json.loads(on_disk[name]) == json.loads(text), name


def test_every_event_type_has_a_schema():
    schema = json.loads((SCHEMA_DIR / "SseEvent.json").read_text(encoding="utf-8"))
    mapped = set(schema["discriminator"]["mapping"])
    assert mapped == set(EVENT_TYPES)


def test_create_run_request_rules():
    CreateRunRequest(mode="recorded", recording_id="rec-1")
    live = CreateRunRequest(mode="live", goal="g", budget_usd="0.100000")
    assert live.budget_usd == Decimal("0.1")
    assert json.loads(live.model_dump_json())["budget_usd"] == "0.100000"
    for bad in (0.1, "0.1", "0.1000001", "-0.100000", "0.000000"):
        with pytest.raises(ValueError):
            CreateRunRequest(mode="live", goal="g", budget_usd=bad)
    with pytest.raises(ValueError):
        CreateRunRequest(mode="live", goal="g")
    with pytest.raises(ValueError):
        CreateRunRequest(mode="recorded")
    with pytest.raises(ValueError):
        CreateRunRequest(mode="live", goal="g", budget_usd="0.100000", api_key="nope")


def test_fixtures_are_current():
    wanted = _script("gen_api_fixtures").files()
    for name, text in wanted.items():
        assert json.loads((FIXTURES / name).read_text(encoding="utf-8")) == json.loads(text), name


def test_the_recorded_bundle_validates():
    bundle = _load("recorded_run.json")
    assert set(bundle) == {"_fixture", *BUNDLE_SECTIONS}
    for section, schema in BUNDLE_SECTIONS.items():
        SCHEMA_MODELS[schema].model_validate(bundle[section])


def test_the_sse_replay_validates_and_keeps_order():
    replay = _load("recorded_run.events.json")
    events = [SSE_EVENT_ADAPTER.validate_python(item["event"]) for item in replay["events"]]
    assert all(item["delay_ms"] >= 0 for item in replay["events"])
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert all(e.id == f"{e.run_id}:{e.seq}" and e.run_id == replay["run_id"] for e in events)
    assert [e.ts for e in events] == sorted(e.ts for e in events)
    assert events[0].type == "run_started" and events[-1].type in TERMINAL_EVENTS
    assert sum(e.type in TERMINAL_EVENTS for e in events) == 1


def test_the_replay_covers_the_required_cases():
    events = [item["event"] for item in _load("recorded_run.events.json")["events"]]
    types = {e["type"] for e in events}
    assert {
        "agent_hired",
        "tool_called",
        "attempt_recorded",
        "audit_result",
        "budget_update",
        "message",
        "task_result",
        "mode_notice",
        "budget_allocation",
        "budget_exhausted",
        "escalation",
    } <= types
    reasons = {e["payload"]["attempt"]["reason"] for e in events if e["type"] == "attempt_recorded"}
    assert reasons == {"first", "repair", "escalation"}
    labels = {e["payload"]["label"] for e in events if e["type"] == "task_result"}
    assert labels == {"first_pass_ok", "ok_after_escalation", "failed"}
    actions = {e["payload"]["action"] for e in events if e["type"] == "budget_allocation"}
    assert actions == {"allocated", "released"}
    stop = next(e for e in events if e["type"] == "budget_exhausted")["payload"]
    assert stop["scope"] == "budget"
    assert Decimal(stop["committed_usd"]) + Decimal(stop["requested_usd"]) > Decimal(
        stop["cap_usd"]
    )
    assert next(e for e in events if e["type"] == "run_finished")["payload"]["partial"] is True
    audit = next(e for e in events if e["type"] == "audit_result")["payload"]["audit"]
    assert audit["verdict"] == "accepted"
    assert any(
        e["type"] == "budget_update" and e["payload"]["entry"]["usage_estimated"] for e in events
    )


def _usd(items, key):
    return sum((Decimal(item[key]) for item in items), ZERO_USD)


def test_the_numbers_add_up_exactly():
    bundle = _load("recorded_run.json")
    events = [item["event"] for item in _load("recorded_run.events.json")["events"]]
    entries = bundle["ledger"]["entries"]
    spent = _usd(entries, "usd_real")
    assert Decimal(bundle["run"]["spent_usd"]) == spent
    assert Decimal(bundle["ledger"]["spent_usd"]) == spent
    assert Decimal(bundle["package"]["cost_report"]["real_usd"]) == spent
    by_level = bundle["ledger"]["spent_by_level"]
    assert sum((Decimal(v) for v in by_level.values()), ZERO_USD) == spent
    last_budget = [e for e in events if e["type"] == "budget_update"][-1]["payload"]
    assert Decimal(last_budget["spent_usd"]) == spent
    finished = next(e for e in events if e["type"] == "run_finished")["payload"]
    assert Decimal(finished["spent_usd"]) == spent
    assert Decimal(finished["predicted_usd"]) == _usd(entries, "usd_predicted")
    assert bundle["ledger"]["usage_estimated_entries"] == sum(e["usage_estimated"] for e in entries)
    for task in bundle["tasks"]["items"]:
        attempts_usd = _usd(task["attempts"], "usd")
        assert Decimal(task["result"]["usage"]["usd"]) == attempts_usd
        task_entries = [e for e in entries if e["task_id"] == task["task"]["task_id"]]
        assert attempts_usd == _usd(task_entries, "usd_real")


MONEY_MAPS = ("spent_by_level", "level_usd")


def _is_money_key(key: str) -> bool:
    return key == "usd" or key.startswith("usd_") or key.endswith("_usd") or "_usd_" in key


def _walk(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")
    else:
        yield path, value


def test_money_is_a_six_decimal_string_and_no_float_is_left():
    pattern = re.compile(USD_PATTERN)
    for path in sorted(FIXTURES.glob("*.json")):
        money = 0
        for where, value in _walk(json.loads(path.read_text(encoding="utf-8"))):
            key = where.rsplit(".", 1)[-1]
            parent = where.rsplit(".", 2)[-2] if where.count(".") >= 2 else ""
            if _is_money_key(key) or parent in MONEY_MAPS:
                assert isinstance(value, str) and pattern.fullmatch(value), (path.name, where)
                money += 1
            elif isinstance(value, float):
                # The prediction error is a ratio, not money: the only number allowed.
                assert key == "prediction_error", (path.name, where, value)
        assert money > 0, path.name


def test_every_money_field_in_the_schemas_is_a_decimal_string():
    found = 0
    for path in sorted(SCHEMA_DIR.glob("*.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        for definition in [schema, *schema.get("$defs", {}).values()]:
            for name, prop in definition.get("properties", {}).items():
                if not _is_money_key(name) and name not in MONEY_MAPS:
                    continue
                options = prop.get("anyOf", [prop])
                for option in options:
                    if option.get("type") == "null":
                        continue
                    if name in MONEY_MAPS:
                        option = option["additionalProperties"]
                    assert option["type"] == "string", (path.name, name)
                    assert option["pattern"] == USD_PATTERN, (path.name, name)
                    found += 1
    assert found >= 30


def test_a_json_number_in_a_money_field_is_refused():
    entry = _load("recorded_run.json")["ledger"]["entries"][0]
    SCHEMA_MODELS["LedgerView"].model_validate(_load("recorded_run.json")["ledger"])
    for bad in (0.0048, 0, "0.0048", "4.8e-3", "0.0048000"):
        with pytest.raises(ValueError):
            SCHEMA_MODELS["LedgerView"].model_validate(
                _load("recorded_run.json")["ledger"] | {"entries": [entry | {"usd_real": bad}]}
            )


def test_the_refused_live_example_validates():
    refused = _load("live_refused.json")
    request = CreateRunRequest.model_validate(refused["request"])
    assert request.mode == "live" and refused["status"] == 429
    error = SCHEMA_MODELS["ErrorResponse"].model_validate(refused["response"])
    assert error.error.code == "live_refused"
    modes = SCHEMA_MODELS["ModesView"].model_validate(refused["modes"])
    live = next(m for m in modes.modes if m.mode == "live")
    assert not live.available and live.refusal == "daily_cap_reached"
    stream = [
        SSE_EVENT_ADAPTER.validate_python(i["event"])
        for i in refused["refused_after_creation"]["events"]
    ]
    assert [e.type for e in stream] == ["mode_notice", "run_failed"]


def test_fixtures_are_labelled_synthetic_and_carry_nothing_secret():
    for path in sorted(FIXTURES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["_fixture"]["synthetic"] is True, path.name
        text = path.read_text(encoding="utf-8")
        assert find_secrets(text, env_secrets()) == [], path.name
        lowered = text.lower()
        # Raw prompts and model internals: chat roles, reasoning, request bodies.
        for forbidden in (
            '"role": "system"',
            '"role": "assistant"',
            '"role": "tool"',
            '"reasoning"',
            '"reasoning_content"',
            '"chat_template_kwargs"',
            '"prompt"',
            "authorization",
            "bearer",
            "api_key",
            "tokenfactory",
        ):
            assert forbidden not in lowered, (path.name, forbidden)
    bundle = _load("recorded_run.json")
    for message in bundle["messages"]["items"]:
        assert message["text"].startswith("[synthetic]")
    for deliverable in bundle["package"]["deliverables"]:
        assert deliverable["title"].startswith("[synthetic]")


def _section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_every_example_in_the_api_doc_validates():
    text = (ROOT / "docs" / "api.md").read_text(encoding="utf-8")
    catalog = _section(text, "### Event catalog", "## Errors")
    blocks = [json.loads(b.split("```", 1)[0]) for b in catalog.split("```json\n")[1:]]
    seen = {SSE_EVENT_ADAPTER.validate_python(b).type for b in blocks}
    assert seen == set(EVENT_TYPES)
    refused = _load("live_refused.json")["refused_after_creation"]["events"]
    fixture_events = [i["event"] for i in _load("recorded_run.events.json")["events"] + refused]
    for block in blocks:  # copied from the fixtures, not written by hand
        assert block in fixture_events, block["id"]
    errors = _section(text, "## Errors", "## Cancellation")
    example = errors.split("```json\n", 1)[1].split("```", 1)[0]
    SCHEMA_MODELS["ErrorResponse"].model_validate_json(example)


def test_recorded_runs_are_labelled_recorded_everywhere():
    bundle = _load("recorded_run.json")
    assert bundle["run"]["mode"] == "recorded"
    for section in ("org", "ledger", "messages", "tasks", "package"):
        assert bundle[section]["mode"] == "recorded", section
    events = [item["event"] for item in _load("recorded_run.events.json")["events"]]
    assert {e["mode"] for e in events} == {"recorded"}
    assert events[0]["payload"]["mode"] == "recorded"


def test_run_ids_are_prefixed_and_the_visitor_limit_example_validates():
    bundle = _load("recorded_run.json")
    refused = _load("live_refused.json")
    assert bundle["run"]["run_id"].startswith("run_")
    assert refused["refused_after_creation"]["run_id"].startswith("run_")
    visitor = refused["visitor_limit"]
    assert visitor["status"] == 429
    error = SCHEMA_MODELS["ErrorResponse"].model_validate(visitor["response"])
    assert error.error.details["refusal"] == "visitor_limit_reached"
    modes = SCHEMA_MODELS["ModesView"].model_validate(visitor["modes"])
    assert modes.live_caps.max_runs_per_visitor_per_day == 1
    assert modes.live_caps.visitor_runs_today == 1
    live = next(m for m in modes.modes if m.mode == "live")
    assert (live.available, live.refusal) == (False, "visitor_limit_reached")
