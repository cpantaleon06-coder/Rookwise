"""Validation, repair and escalation with per-attempt records. Scripted fake model."""

import dataclasses
import json
import random

from harness_support import (
    TEST_KEY,
    FakeClock,
    config,
    content,
    final_action,
    finish,
    ledger,
    replies,
    request,
    role,
    run,
    sse,
    text_reply,
)
from pydantic import BaseModel, ConfigDict

from rookwise.harness import Harness, ToolLoop
from rookwise.harness.escalate import run_with_escalation
from rookwise.harness.validate import (
    build_result,
    final_result_instructions,
    validate_final,
)
from rookwise.schemas import TaskV1

NANO = "nemotron-3-nano"
SUPER = "nemotron-3-super"
ULTRA = "nemotron-3-ultra"


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sum: int


def ok(value=42, notes=""):
    return {"status": "ok", "output": {"sum": value}, "notes": notes}


def _run(handler, *, model=NANO, cfg=None, book=None):
    cfg = cfg or config()
    book = book or ledger()

    async def main():
        harness = Harness(
            book,
            config=cfg,
            api_key=TEST_KEY,
            transport=handler.transport(),
            clock=FakeClock(),
            rng=random.Random(0),
        )
        async with harness:
            req = request(
                model=model,
                max_tokens=64,
                messages=[
                    {"role": "system", "content": "Test operator."},
                    {"role": "user", "content": "17 + 25?"},
                ],
            )
            return await run_with_escalation(ToolLoop(harness), req, Answer, config=cfg.escalation)

    result = run(main())
    report = book.report("r-1")
    assert report.held_usd == 0
    return result, report


def _no_repairs():
    cfg = config()
    return dataclasses.replace(cfg, escalation=dataclasses.replace(cfg.escalation, max_repairs=0))


def test_validate_final_lists_errors_and_checks_status():
    good = validate_final(ok(), Answer)
    assert good.ok and good.operator_ok
    reported = validate_final({"status": "failed", "output": {"sum": 0}, "notes": "no"}, Answer)
    assert reported.ok and not reported.operator_ok
    bad = validate_final({"status": "ok", "output": {"sum": "x"}, "extra": 1}, Answer)
    assert not bad.ok
    assert any(e.startswith("output.sum:") for e in bad.errors)
    assert any(e.startswith("extra:") for e in bad.errors)
    assert validate_final(None, Answer).errors == ("(root): no final result",)
    assert '"sum"' in final_result_instructions(Answer)


def test_build_result_validates_against_result_v1():
    task = TaskV1.model_validate(
        {
            "task_id": "t-1",
            "run_id": "r-1",
            "role": "researcher",
            "instruction_ref": "store://r-1/briefs/t-1",
            "inputs": [],
            "budget": {"max_input_tokens": 1, "max_output_tokens": 1, "max_usd": 1.0},
            "deadline_s": 60,
        }
    )
    result = build_result(
        task,
        status="ok",
        output_ref="store://r-1/results/t-1",
        input_tokens=10,
        output_tokens=5,
        usd=0.001,
        schema_valid=True,
        notes="first_pass_ok",
    )
    assert result.task_id == "t-1" and result.usage.usd == 0.001


def test_first_pass_ok():
    result, report = _run(replies(text_reply(final_action(ok()))))
    assert result.label == "first_pass_ok" and result.validation.payload.output.sum == 42
    (attempt,) = result.attempts
    assert (attempt.reason, attempt.retry_reason, attempt.ok) == ("first", None, True)
    assert attempt.usd == report.entries[0].usd_real and attempt.usage_estimated is False


def test_repair_then_success_is_ok_after_retry():
    handler = replies(
        text_reply(final_action({"status": "ok", "output": {"sum": "forty-two"}})),
        text_reply(final_action(ok())),
    )
    result, report = _run(handler)
    assert result.label == "ok_after_retry"
    first, repair = result.attempts
    assert (first.ok, first.loop_status) == (False, "final")
    assert any(e.startswith("output.sum:") for e in first.validation_errors)
    assert (repair.reason, repair.retry_reason, repair.ok, repair.model) == (
        "repair",
        "validation_failed",
        True,
        NANO,
    )
    feedback = handler.bodies[1]["messages"][-1]["content"]
    assert feedback.startswith("VALIDATION ERROR") and "output.sum" in feedback
    assert "as a final action" in feedback
    assert sum(a.usd for a in result.attempts) == sum(e.usd_real for e in report.entries)


def test_a_length_retry_on_the_first_model_is_ok_after_retry():
    handler = replies(
        text_reply("thinking...", completion=64, reason="length"),
        text_reply(final_action(ok())),
    )
    result, _ = _run(handler)
    assert result.label == "ok_after_retry" and result.attempts[0].length_retries == 1


def test_escalation_then_success_after_the_repairs_run_out():
    bad = text_reply(final_action({"status": "ok", "output": {}}))
    repairs = config().escalation.max_repairs
    handler = replies(*[bad] * (repairs + 1), text_reply(json.dumps(ok())))
    result, report = _run(handler)
    assert result.label == "ok_after_escalation" and result.final_model == SUPER
    assert [(a.model, a.reason, a.retry_reason) for a in result.attempts] == [
        (NANO, "first", None),
        *[(NANO, "repair", "validation_failed")] * repairs,
        (SUPER, "escalation", "validation_failed"),
    ]
    assert result.attempts[-1].protocol == "native_tools"
    escalated = handler.bodies[repairs + 1]
    assert escalated["model"] == config().model(SUPER).model_id
    assert [m["role"] for m in escalated["messages"]] == ["system", "user"]
    assert [e.model for e in report.entries] == [NANO] * (repairs + 1) + [SUPER]


def test_length_twice_escalates_as_a_failure():
    handler = replies(
        text_reply("cut", completion=64, reason="length"),
        text_reply("cut", completion=128, reason="length"),
        text_reply(json.dumps(ok())),
    )
    result, _ = _run(handler)
    assert result.label == "ok_after_escalation"
    assert result.attempts[0].loop_status == "length"
    assert result.attempts[1].retry_reason == "length"


def test_operator_reported_failure_escalates_without_repair():
    handler = replies(
        text_reply(final_action({"status": "failed", "output": {"sum": 0}, "notes": "unsure"})),
        text_reply(json.dumps(ok())),
    )
    result, _ = _run(handler)
    assert [a.reason for a in result.attempts] == ["first", "escalation"]
    assert result.attempts[1].retry_reason == "operator_reported_failure"


def test_escalation_blocked_by_budget():
    # Nano's invalid answer reports 25,000 prompt tokens: USD 0.0015 plus output passes
    # the USD 0.0015 run cap, so the ledger refuses Super's reservation.
    book = ledger(run_usd=0.0015)
    handler = replies(text_reply(final_action({"status": "ok", "output": {}}), prompt=25_000))
    result, report = _run(handler, cfg=_no_repairs(), book=book)
    assert result.label == "failed" and result.stop_reason == "budget_exhausted"
    last = result.attempts[-1]
    assert (last.model, last.loop_status, last.model_calls, last.usd) == (
        SUPER,
        "budget_exhausted",
        0,
        0.0,
    )
    assert len(handler.requests) == 1 and len(report.entries) == 1


def test_top_of_the_ladder_fails():
    handler = replies(text_reply('{"status": "ok", "output": {}}'))
    result, _ = _run(handler, model=ULTRA, cfg=_no_repairs())
    assert result.label == "failed" and result.stop_reason == "top_of_ladder"


def test_usage_estimated_propagates_to_attempts_and_the_ledger():
    no_usage = sse([role(), content(final_action(ok())), finish()])
    result, report = _run(replies(no_usage))
    assert result.label == "first_pass_ok"
    assert result.attempts[0].usage_estimated is True
    assert report.entries[0].usage_estimated is True
