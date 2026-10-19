"""The run report of scripts/team_smoke.py keeps every audited citation and the full reply
text of every attempt that ended in a validation or protocol error. Stub data only, no
network."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import httpx

from rookwise.harness import AttemptRecord

ROOT = Path(__file__).resolve().parents[1]
JUNK = "This is not JSON at all."


def _script():
    spec = importlib.util.spec_from_file_location("team_smoke", ROOT / "scripts" / "team_smoke.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["team_smoke"] = module
    spec.loader.exec_module(module)
    return module


def _multi_line_payload() -> str:
    claim = {
        "claim_id": "c1",
        "text": "[stub] The pool size was cut.",
        "citations": [
            {
                "source_id": "app-log",
                "line_start": 13,
                "line_end": 14,
                "quote": "config_version=42\ndb.pool.max_connections: 50 -> 5",
            }
        ],
    }
    output = {"summary": "[stub] Findings.", "claims": [claim]}
    return json.dumps({"status": "ok", "output": output, "notes": ""})


def _scripted(module, overrides):
    """The estimate stub, except that operator call number n gets `overrides[n]`."""
    stub = module._stub_transport().handler
    count = {"operator": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        system = json.loads(request.content)["messages"][0]["content"]
        if system.startswith(module.OPERATOR_PROMPT):
            count["operator"] += 1
            text = overrides.get(count["operator"])
            if text is not None:
                return httpx.Response(
                    200,
                    content=module._sse(text, 4000, 300),
                    headers={"content-type": "text/event-stream"},
                )
        return stub(request)

    return httpx.MockTransport(handle)


def test_each_audited_citation_is_kept_with_its_quote_and_reason(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    module = _script()
    report, _, calls = asyncio.run(module.run("estimate", module.load_scenario()))
    citations = report["citations"]
    # Four operator tasks with one citation each, then the director's one citation.
    assert [c["agent"] for c in citations] == ["operator"] * 4 + ["director"]
    assert citations[-1]["withdrawn"] is False and citations[-1]["status"] == "verified"
    assert report["diagnosis_status"] == "audited" and report["withdrawn_claims"] == []
    assert report["claim_counts"] == {"supported": 1, "withdrawn": 0, "by_reason": {}}
    first = citations[0]
    assert {k: first[k] for k in ("source_id", "line_start", "line_end", "quote")} == {
        "source_id": "app-log",
        "line_start": 14,
        "line_end": 14,
        "quote": "db.pool.max_connections: 50 -> 5",
    }
    assert (first["reason"], first["status"]) == ("ok", "verified")
    assert first["claim_id"] == "t-1:c1" and first["model"] == "nemotron-3.5-lightning"
    assert report["error_replies"] == []
    assert all(module.REPLY_TEXT not in call for call in calls)  # calls.json stays as it was


def test_validation_and_protocol_errors_keep_the_full_reply_text(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    module = _script()
    long_junk = JUNK + " x" * 3000  # never truncated
    # t-1: an invalid reply, then a multi-line quote (a validation error), then the stub's
    # good reply as the repair. t-2: three invalid replies end its attempt as a protocol
    # error, and the stub answers on the next model of the ladder.
    overrides = {1: long_junk, 2: _multi_line_payload(), 4: JUNK, 5: JUNK, 6: JUNK}
    transport = _scripted(module, overrides)
    monkeypatch.setattr(module, "_stub_transport", lambda: transport)
    report, _, calls = asyncio.run(module.run("estimate", module.load_scenario()))
    found = {(e["task_id"], e["kind"]): e for e in report["error_replies"]}
    assert set(found) == {("t-1", "validation_error"), ("t-2", "protocol_error")}
    invalid = found[("t-1", "validation_error")]
    assert invalid["model"] == "nemotron-3.5-lightning"
    assert [r["text"] for r in invalid["replies"]] == [long_junk, _multi_line_payload()]
    assert any("single line" in e for e in invalid["validation_errors"])
    protocol = found[("t-2", "protocol_error")]
    assert [r["text"] for r in protocol["replies"]] == [JUNK] * 3
    assert all(r["model"] == "nemotron-3.5-lightning" for r in protocol["replies"])
    # The multi-line quote never reached the audit: only the repaired claims did.
    assert all("\n" not in c["quote"] for c in report["citations"])
    assert all(module.REPLY_TEXT not in call for call in calls)


def _attempt(task_id, index, status, calls, errors=()):
    return AttemptRecord(
        task_id=task_id,
        attempt_index=index,
        model="nemotron-3.5-lightning",
        protocol="native_tools",
        reason="first" if index == 0 else "repair",
        retry_reason=None,
        loop_status=status,
        ok=False,
        validation_errors=list(errors),
        length_retries=0,
        steps=calls,
        model_calls=calls,
        tool_calls={},
        usd="0.000001",
        input_tokens=1,
        output_tokens=1,
        usage_estimated=False,
    )


def test_replies_are_matched_to_attempts_per_task_in_call_order():
    module = _script()
    calls = [
        {"task_id": "t-1", "model": "m", "counted": True, module.REPLY_TEXT: "a"},
        {"task_id": "t-2", "model": "m", "counted": True, module.REPLY_TEXT: "x"},
        {"task_id": "t-1", "model": "m", "counted": True, module.REPLY_TEXT: "b"},
        {"task_id": "t-1", "model": "m", "counted": False, "raised": "refused"},
        {"task_id": "t-1", "model": "m", "counted": True, module.REPLY_TEXT: "c"},
    ]
    attempts = [
        ("a-op-t-1", _attempt("t-1", 0, "final", 2, ["output.summary: Field required"])),
        ("a-op-t-2", _attempt("t-2", 0, "budget_exhausted", 1)),
        ("a-op-t-1", _attempt("t-1", 1, "protocol_error", 1)),
    ]
    found = module.error_replies(attempts, calls)
    assert [(f["task_id"], f["kind"], [r["text"] for r in f["replies"]]) for f in found] == [
        ("t-1", "validation_error", ["a", "b"]),
        ("t-1", "protocol_error", ["c"]),
    ]
