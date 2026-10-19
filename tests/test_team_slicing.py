"""The team assigns one slice per operator task and reports what was not read. Stub
transport and a small synthetic bundle built here; no network, no gitignored logs."""

import dataclasses
import json

from harness_support import text_reply
from team_stub import (
    TeamHandler,
    findings_payload,
    findings_reply,
    judgment_reply,
    operator,
    plan_reply,
    run_stub_team,
    summary_reply,
)

from rookwise.evidence import EvidenceBundle
from rookwise.harness import load_config
from rookwise.harness.config import EscalationConfig
from rookwise.slicing import SlicingConfig, coverage, slice_bundle
from rookwise.team.flow import UnreadRange, slice_ref

# SYNTHETIC: a 30-line log and a 4-line diff; each log line has a unique value.
APP = "".join(
    f"2026-03-04T02:00:{n:02d}Z INFO worker step={n} value=v{n:03d}\n" for n in range(1, 31)
)
DIFF = "--- a/settings.conf\n+++ b/settings.conf\n-limit = 50\n+limit = 5\n"
BUNDLE = EvidenceBundle(sources={"app.log": APP, "deploy.diff": DIFF})
SLICING = SlicingConfig(max_slice_tokens=250, overlap_lines=2, chars_per_token=2.7, headroom=0.1)
SLICES = slice_bundle(BUNDLE.sources, SLICING).slices
APP_SLICES = [s for s in SLICES if s.source_id == "app.log"]


def _block(source_id, goal="[stub] Read a source."):
    task = {"role": "stub-operator", "source_id": source_id, "instruction": "[stub] Read it."}
    return {"goal": goal, "tasks": [task]}


def _plan():
    return plan_reply(_block("app.log"), _block("deploy.diff"))


def _empty_findings():
    return findings_reply()


def _run(handler, **kwargs):
    kwargs.setdefault("bundle", BUNDLE)
    kwargs.setdefault("slicing", SLICING)
    return run_stub_team(handler, run_usd="0.5", **kwargs)


def _payloads(team, kind):
    return [e.payload for e in team.events if e.type == kind]


def test_each_slice_goes_to_its_own_operator_with_only_that_slice():
    assert len(APP_SLICES) >= 3  # the small budget cuts the log into several slices
    handler = TeamHandler(
        director=[_plan()],
        operator=[_empty_findings() for _ in SLICES],
        manager=[summary_reply(), summary_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = _run(handler)
    assigned = _payloads(team, "task_assigned")
    assert [a.task.inputs for a in assigned] == [[slice_ref(team.run_id, s)] for s in SLICES]
    assert [t.slice for b in team.blocks for t in b.tasks] == list(SLICES)
    bodies = [b for b in handler.bodies if "Task t-" in b["messages"][-1]["content"]]
    assert len(bodies) == len(SLICES)
    for body, item in zip(bodies, SLICES, strict=True):
        user = body["messages"][-1]["content"]
        assert item.text in user
        assert f"lines {item.line_start}-{item.line_end} of {item.line_count}" in user
        if item.source_id == "app.log":
            outside = [n for n in range(1, 31) if not item.line_start <= n <= item.line_end]
            assert not any(f"value=v{n:03d}" in user for n in outside)
            assert "+limit = 5" not in user  # nor any other source
    assert team.unread_slices == [] and team.empty_sources == []
    plan_message = _payloads(team, "message")[0].message.text
    assert f"over {len(SLICES)} slices" in plan_message


def test_the_plan_must_read_every_source_and_is_repaired_when_it_does_not():
    handler = TeamHandler(
        director=[plan_reply(_block("app.log")), plan_reply(_block("nope.log")), _plan()],
        operator=[_empty_findings() for _ in SLICES],
        manager=[summary_reply(), summary_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = _run(handler)
    attempts = [
        p.attempt for p in _payloads(team, "attempt_recorded") if p.attempt.task_id == "plan"
    ]
    assert [a.reason for a in attempts] == ["first", "repair", "repair"]
    assert any("no task reads deploy.diff" in e for e in attempts[0].validation_errors)
    assert any("there is no source 'nope.log'" in e for e in attempts[1].validation_errors)
    assert attempts[2].ok and team.status == "finished"
    request = handler.bodies[0]["messages"][-1]["content"]
    assert f"- app.log: 30 lines, {len(APP_SLICES)} slices" in request
    assert "- deploy.diff: 4 lines, 1 slices" in request


def test_lines_no_completed_task_read_are_reported_as_unread():
    failed = text_reply(findings_payload(status="failed"))
    replies = [_empty_findings() for _ in SLICES]
    replies[1] = failed  # the second slice of the log
    no_ladder = dataclasses.replace(load_config(env={}), escalation=EscalationConfig(0, {}))
    handler = TeamHandler(
        director=[_plan()],
        operator=replies,
        manager=[summary_reply(), summary_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = _run(handler, harness_config=no_ladder, catalog=[operator("stub-op-a", "0.001")])
    second = APP_SLICES[1]
    (task,) = [t for b in team.blocks for t in b.tasks if t.slice == second]
    assert task.status == "failed"
    others = [s for s in APP_SLICES if s != second]
    expected = [UnreadRange("app.log", a, b) for a, b in coverage(others, 30)]
    assert expected and team.unread_slices == expected
    # The overlap keeps the boundary lines read by the neighbours.
    (gap,) = expected
    assert second.line_start < gap.line_start and gap.line_end < second.line_end
    closing = _payloads(team, "message")[-1].message.text
    assert f"Unread lines: app.log {gap.line_start}-{gap.line_end}." in closing


def test_an_empty_source_has_no_task_and_is_listed():
    bundle = EvidenceBundle(sources={"app.log": APP, "empty.txt": ""})
    slices = [s for s in SLICES if s.source_id == "app.log"]
    handler = TeamHandler(
        director=[plan_reply(_block("app.log"))],
        operator=[_empty_findings() for _ in slices],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = _run(handler, bundle=bundle)
    assert team.empty_sources == ["empty.txt"] and team.unread_slices == []
    assert "- empty.txt: empty, nothing to read" in handler.bodies[0]["messages"][-1]["content"]


def test_citations_are_validated_against_the_full_source_not_the_slice():
    # The operator of the first slice cites line 30, which is outside its slice.
    far = {
        "claim_id": "c1",
        "text": "[stub] The last step.",
        "citations": [
            {
                "source_id": "app.log",
                "line_start": 30,
                "line_end": 30,
                "quote": "2026-03-04T02:00:30Z INFO worker step=30 value=v030",
            }
        ],
    }
    assert APP_SLICES[0].line_end < 30
    replies = [_empty_findings() for _ in SLICES]
    replies[0] = text_reply(findings_payload(far))
    handler = TeamHandler(
        director=[_plan()],
        operator=replies,
        manager=[summary_reply(), summary_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = _run(handler)
    first = next(
        p.attempt for p in _payloads(team, "attempt_recorded") if p.attempt.task_id == "t-1"
    )
    assert first.ok and first.reason == "first"
    assert team.evidence.all_supported and team.evidence.citations_total == 1


def test_the_task_carries_the_slice_reference_in_its_inputs_only():
    handler = TeamHandler(
        director=[_plan()],
        operator=[_empty_findings() for _ in SLICES],
        manager=[summary_reply(), summary_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = _run(handler)
    task = _payloads(team, "task_assigned")[0].task
    assert task.inputs == [f"store://{team.run_id}/slices/{APP_SLICES[0].slice_id}"]
    assert json.loads(task.model_dump_json())["inputs"] == task.inputs  # contract v1 shape
