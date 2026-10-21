"""Actionable re-prompts for replies that are not valid JSON, and the guard against a
reply byte-identical to the previous invalid one. Stub transport; no network."""

import json
import random

from harness_support import TEST_KEY, FakeClock, config, ledger, replies, request, run, text_reply
from test_harness_escalate import Answer, ok

from rookwise.harness import Harness, ToolLoop
from rookwise.harness.escalate import run_with_escalation
from rookwise.harness.loop import open_brackets, parse_json_text

ULTRA, SUPER = "nemotron-3-ultra", "nemotron-3-super"
# SYNTHETIC: the shape of the first inc-01 plan reply: "notes" lands inside "output"
# because one closing brace is missing, so the parser stops only at the end.
BAD = '{"status": "ok", "output": {"summary": "x", "blocks": [{"goal": "g"}], "notes": ""}'


def _loop(handler, *, model=ULTRA, book=None):
    book = book or ledger()

    async def main():
        harness = Harness(
            book,
            config=config(),
            api_key=TEST_KEY,
            transport=handler.transport(),
            clock=FakeClock(),
            rng=random.Random(0),
        )
        async with harness:
            req = request(
                model=model,
                messages=[
                    {"role": "system", "content": "Test director."},
                    {"role": "user", "content": "Plan."},
                ],
            )
            return await ToolLoop(harness).run(req)

    return run(main()), book


def test_the_reprompt_quotes_the_error_position_and_the_text_around_it():
    handler = replies(text_reply(BAD), text_reply(json.dumps(ok())))
    outcome, _ = _loop(handler)
    assert outcome.status == "final"
    feedback = handler.bodies[1]["messages"][-1]["content"]
    assert feedback.startswith(
        "PROTOCOL ERROR: the reply is not valid JSON: Expecting ',' delimiter"
    )
    assert f"at the end of the reply (character {len(BAD)} of {len(BAD)})" in feedback
    assert '"blocks": [{"goal": "g"}], "notes": ""}<<ERROR HERE>>' in feedback
    assert "1 bracket(s) are still open, outermost first: {" in feedback
    assert "the complete corrected final result as one JSON object" in feedback
    assert "not only the part you fixed" in feedback


def test_an_error_inside_the_reply_gives_its_line_and_column():
    _, problem = parse_json_text('{"a": 1,\n "b" 2}')
    assert "Expecting ':' delimiter at line 2, column 6 (character 14 of 16)" in problem
    assert '{"a": 1,\n "b" <<ERROR HERE>>2}' in problem
    assert "still open" not in problem  # the closer matches: nothing is left open


def test_open_brackets_ignore_strings_and_give_up_on_a_mismatch():
    assert open_brackets('{"a": ["}{", {') == ["{", "[", "{"]
    assert open_brackets('{"a": "\\"]"}') == []
    assert open_brackets('{"a": [1}') == []  # a closer that does not match: no count


def test_a_reply_identical_to_the_previous_invalid_one_stops_the_run():
    handler = replies(text_reply(BAD), text_reply(BAD), text_reply(BAD))
    outcome, book = _loop(handler)
    assert outcome.status == "repeated_invalid_reply"
    assert outcome.detail.startswith("the reply is not valid JSON")
    assert len(handler.bodies) == 2 and outcome.model_calls == 2  # the third is not sent
    assert [t["kind"] for t in outcome.trace] == ["protocol_error", "repeated_invalid_reply"]
    report = book.report("r-1")
    assert len(report.entries) == 2 and report.held_usd == 0  # both calls charged as usual


def test_a_different_invalid_reply_gets_the_reprompt_again():
    handler = replies(text_reply(BAD), text_reply(BAD + " "), text_reply(json.dumps(ok())))
    outcome, _ = _loop(handler)
    assert outcome.status == "final" and len(handler.bodies) == 3


def test_a_repeated_invalid_reply_moves_up_the_ladder():
    handler = replies(text_reply(BAD), text_reply(BAD), text_reply(json.dumps(ok())))
    book = ledger()

    async def main():
        harness = Harness(
            book,
            config=config(),
            api_key=TEST_KEY,
            transport=handler.transport(),
            clock=FakeClock(),
            rng=random.Random(0),
        )
        async with harness:
            req = request(model=SUPER, messages=[{"role": "user", "content": "17 + 25?"}])
            return await run_with_escalation(
                ToolLoop(harness), req, Answer, config=config().escalation
            )

    result = run(main())
    assert result.ok and result.final_model == ULTRA
    assert [a.loop_status for a in result.attempts] == ["repeated_invalid_reply", "final"]
    assert result.attempts[1].retry_reason == "repeated_invalid_reply"
