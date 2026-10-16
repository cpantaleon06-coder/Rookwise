"""The tool loop against a scripted fake model: both protocols, tool failures, limits,
length handling (D3), budgets, cancellation and replay. No network."""

import asyncio
import dataclasses
import json
import random

import pytest
from harness_support import (
    LIGHTNING,
    TEST_KEY,
    FakeClock,
    Handler,
    config,
    final_action,
    ledger,
    replies,
    request,
    respond,
    run,
    text_reply,
    tool_action,
    tool_reply,
)

from rookwise.harness import CancelHandle, Harness
from rookwise.harness.cassette import Cassette
from rookwise.harness.loop import (
    PROTOCOL_HEADING,
    TokenBudget,
    Tool,
    ToolLoop,
    parse_action,
)

NANO = "nemotron-3-nano"


def _harness(handler, book, *, cfg=None, cassette=None):
    return Harness(
        book,
        config=cfg or config(),
        api_key=TEST_KEY if cassette is None or cassette.mode != "replay" else None,
        transport=handler.transport() if handler is not None else None,
        clock=FakeClock(),
        rng=random.Random(0),
        cassette=cassette,
    )


def _add_tool(calls=None, handler=None, **kwargs):
    async def add(args, ctx):
        if calls is not None:
            calls.append((args, ctx.task_id))
        return args["a"] + args["b"]

    schema = {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    }
    return Tool("add", "Add two integers.", schema, handler or add, **kwargs)


def _messages():
    return [
        {"role": "system", "content": "You are a test operator."},
        {"role": "user", "content": "What is 17 + 25?"},
    ]


def _loop_run(
    handler, tools, *, model=NANO, book=None, cfg=None, budget=None, cancel=None, **overrides
):
    book = book or ledger()

    async def main():
        async with _harness(handler, book, cfg=cfg) as harness:
            loop = ToolLoop(harness, tools)
            req = request(model=model, messages=_messages(), **overrides)
            return await loop.run(req, budget=budget, cancel=cancel)

    return run(main()), book


def _held_zero(book):
    report = book.report("r-1")
    assert report.held_usd == 0
    return report


def test_json_protocol_happy_path():
    calls = []
    handler = replies(
        text_reply(tool_action("add", {"a": 17, "b": 25})),
        text_reply(final_action({"sum": 42})),
    )
    outcome, book = _loop_run(handler, [_add_tool(calls)])
    assert outcome.status == "final" and outcome.final == {"sum": 42}
    assert outcome.protocol == "json_protocol" and outcome.steps == 2
    assert calls == [({"a": 17, "b": 25}, "t-1")] and outcome.tool_calls == {"add": 1}
    first = handler.bodies[0]
    assert first["response_format"] == {"type": "json_object"} and "tools" not in first
    assert PROTOCOL_HEADING in first["messages"][0]["content"]
    assert "add: Add two integers." in first["messages"][0]["content"]
    second = handler.bodies[1]["messages"]
    assert second[-1]["role"] == "user" and second[-1]["content"].startswith("TOOL RESULT for add")
    assert json.loads(second[-1]["content"].split("\n", 1)[1]) == {"ok": True, "result": 42}
    report = _held_zero(book)
    assert len(report.entries) == 2
    assert outcome.usd == pytest.approx(sum(e.usd_real for e in report.entries))


def test_native_tools_happy_path():
    handler = replies(
        tool_reply([("call_1", "add", '{"a": 17, "b": 25}')]),
        text_reply('{"sum": 42}'),
    )
    outcome, book = _loop_run(handler, [_add_tool()], model=LIGHTNING)
    assert outcome.protocol == "native_tools"
    assert outcome.status == "final" and outcome.final == {"sum": 42}
    first = handler.bodies[0]
    assert first["tools"][0]["function"]["name"] == "add" and first["tool_choice"] == "auto"
    assert "response_format" not in first
    sent = handler.bodies[1]["messages"]
    assert sent[-2]["role"] == "assistant" and sent[-2]["tool_calls"][0]["id"] == "call_1"
    assert sent[-1] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "name": "add",
        "content": '{"ok": true, "result": 42}',
    }
    _held_zero(book)


def test_malformed_action_is_fed_back_then_the_run_continues():
    handler = replies(text_reply("The answer is 42."), text_reply(final_action(42)))
    outcome, _ = _loop_run(handler, [_add_tool()])
    assert outcome.status == "final" and outcome.final == 42
    feedback = handler.bodies[1]["messages"][-1]
    assert feedback["role"] == "user" and feedback["content"].startswith("PROTOCOL ERROR")
    assert [t["kind"] for t in outcome.trace] == ["protocol_error", "final"]


def test_too_many_protocol_errors_stop_the_run():
    limit = config().loop.max_protocol_errors
    handler = replies(*[text_reply("not json") for _ in range(limit + 1)])
    outcome, book = _loop_run(handler, [])
    assert outcome.status == "protocol_error" and outcome.steps == limit + 1
    _held_zero(book)


def test_parse_action_errors_are_specific():
    assert parse_action('```json\n{"action": "final", "result": 1}\n```')[0].result == 1
    assert "action" in parse_action('{"name": "add"}')[1]
    assert "args" in parse_action('{"action": "tool", "name": "x", "args": 3}')[1]
    assert "JSON object" in parse_action("[1, 2]")[1]


def test_unknown_tool_and_bad_args_go_back_as_structured_errors():
    handler = replies(
        text_reply(tool_action("multiply", {"a": 1})),
        text_reply(tool_action("add", {"a": 1})),
        text_reply(final_action("gave up")),
    )
    outcome, _ = _loop_run(handler, [_add_tool()])
    assert outcome.status == "final" and outcome.tool_calls == {}
    unknown = json.loads(handler.bodies[1]["messages"][-1]["content"].split("\n", 1)[1])
    assert unknown["ok"] is False and unknown["error"]["type"] == "unknown_tool"
    assert "add" in unknown["error"]["message"]
    bad = json.loads(handler.bodies[2]["messages"][-1]["content"].split("\n", 1)[1])
    assert bad["error"]["type"] == "bad_args" and "b" in bad["error"]["message"]


def test_native_arguments_that_do_not_parse_are_a_bad_args_result():
    handler = replies(tool_reply([("c", "add", '{"a": 17{}')]), text_reply('{"sum": 0}'))
    outcome, _ = _loop_run(handler, [_add_tool()], model=LIGHTNING)
    result = json.loads(handler.bodies[1]["messages"][-1]["content"])
    assert result["error"]["type"] == "bad_args" and outcome.status == "final"


def test_tool_timeout_and_tool_exception_never_raise():
    async def hangs(args, ctx):
        await asyncio.Event().wait()

    async def breaks(args, ctx):
        raise RuntimeError("disk full")

    slow = Tool("slow", "Hangs.", {"type": "object"}, hangs, timeout_s=0.01)
    broken = Tool("broken", "Raises.", {"type": "object"}, breaks)
    handler = replies(
        text_reply(tool_action("slow", {})),
        text_reply(tool_action("broken", {})),
        text_reply(final_action("done")),
    )
    outcome, book = _loop_run(handler, [slow, broken])
    assert outcome.status == "final"
    timeout = json.loads(handler.bodies[1]["messages"][-1]["content"].split("\n", 1)[1])
    assert timeout["error"]["type"] == "timeout"
    error = json.loads(handler.bodies[2]["messages"][-1]["content"].split("\n", 1)[1])
    assert error["error"] == {"type": "tool_error", "message": "RuntimeError: disk full"}
    _held_zero(book)


def test_long_tool_results_are_truncated_to_the_token_cap():
    async def big(args, ctx):
        return "x" * 10_000

    cfg = dataclasses.replace(
        config(), loop=dataclasses.replace(config().loop, tool_result_max_tokens=50)
    )
    tool = Tool("big", "Returns a lot.", {"type": "object"}, big)
    handler = replies(text_reply(tool_action("big", {})), text_reply(final_action("ok")))
    outcome, _ = _loop_run(handler, [tool], cfg=cfg)
    sent = json.loads(handler.bodies[1]["messages"][-1]["content"].split("\n", 1)[1])
    assert sent["truncated"] is True and sent["original_characters"] > 10_000
    assert len(sent["content"]) == 50 * cfg.chars_per_token
    assert outcome.status == "final"


def test_repeated_identical_calls_stop_the_run():
    calls = []
    same = tool_action("add", {"a": 1, "b": 2})
    handler = replies(*[text_reply(same) for _ in range(3)])
    outcome, book = _loop_run(handler, [_add_tool(calls)])
    assert outcome.status == "repeated_tool_call"
    assert len(calls) == config().loop.max_repeats + 1
    _held_zero(book)


def test_step_limit_stops_the_run():
    steps = config().loop.max_steps
    handler = replies(*[text_reply(tool_action("add", {"a": i, "b": 1})) for i in range(steps)])
    outcome, book = _loop_run(handler, [_add_tool()])
    assert outcome.status == "step_limit" and outcome.steps == steps
    assert len(book.report("r-1").entries) == steps


def test_budget_exhausted_mid_loop_stops_without_a_leaked_hold():
    # The first call reserves little, but reports 25,000 prompt tokens: its real cost
    # (USD 0.0015154) passes the USD 0.0015 cap, so the ledger stops the run scope and
    # the second step's reservation is refused.
    book = ledger(run_usd=0.0015)
    handler = replies(
        text_reply(tool_action("add", {"a": 1, "b": 2}), prompt=25_000, completion=64)
    )
    outcome, _ = _loop_run(handler, [_add_tool()], book=book, max_tokens=64)
    assert outcome.status == "budget_exhausted" and "cap reached" in outcome.detail
    report = _held_zero(book)
    assert len(report.entries) == 1 and len(handler.requests) == 1
    assert outcome.tool_calls == {"add": 1}


def test_token_budget_from_the_ledger_stops_the_run():
    handler = replies(
        text_reply(tool_action("add", {"a": 1, "b": 2}), prompt=100, completion=60),
        text_reply(final_action(3)),
    )
    budget = TokenBudget(max_input_tokens=100_000, max_output_tokens=60)
    outcome, book = _loop_run(handler, [_add_tool()], budget=budget)
    assert outcome.status == "token_ceiling" and len(handler.requests) == 1
    small = TokenBudget(max_input_tokens=10, max_output_tokens=10_000)
    outcome, _ = _loop_run(replies(), [_add_tool()], budget=small)
    assert outcome.status == "token_ceiling"


def test_output_budget_also_caps_max_tokens():
    handler = replies(text_reply(final_action(1)))
    budget = TokenBudget(max_input_tokens=100_000, max_output_tokens=40)
    outcome, _ = _loop_run(handler, [], budget=budget, max_tokens=500)
    assert outcome.status == "final" and handler.bodies[0]["max_tokens"] == 40


def test_length_is_discarded_and_retried_once_with_more_tokens():
    handler = replies(
        text_reply("Here's a thinking process: ...", completion=64, reason="length"),
        text_reply(final_action(42)),
    )
    outcome, book = _loop_run(handler, [], max_tokens=64)
    assert outcome.status == "final" and outcome.final == 42
    assert [b["max_tokens"] for b in handler.bodies] == [64, 128]
    assert outcome.length_retries == 1
    # The truncated reply never reaches the conversation.
    assert all("thinking process" not in m.get("content", "") for m in outcome.messages)
    assert len(_held_zero(book).entries) == 2


def test_length_twice_ends_the_run_as_length():
    handler = replies(
        text_reply("cut", completion=64, reason="length"),
        text_reply("cut again", completion=128, reason="length"),
    )
    outcome, book = _loop_run(handler, [], max_tokens=64)
    assert outcome.status == "length" and outcome.final is None
    assert len(_held_zero(book).entries) == 2


def test_cancel_during_a_tool_settles_and_stops():
    started = asyncio.Event()

    async def waits(args, ctx):
        started.set()
        await asyncio.Event().wait()

    tool = Tool("wait", "Waits.", {"type": "object"}, waits)
    handler = replies(text_reply(tool_action("wait", {})))
    cancel = CancelHandle()
    book = ledger()

    async def main():
        async with _harness(handler, book) as harness:
            loop = ToolLoop(harness, [tool])
            task = asyncio.create_task(
                loop.run(request(model=NANO, messages=_messages()), cancel=cancel)
            )
            await started.wait()
            cancel.cancel()
            return await asyncio.wait_for(task, 2)

    outcome = run(main())
    assert outcome.status == "cancelled"
    assert len(_held_zero(book).entries) == 1


def test_an_unavailable_tool_is_not_offered_and_errors_when_called():
    tool = _add_tool(unavailable=lambda: "ADD_KEY is not set")
    handler = replies(text_reply(tool_action("add", {"a": 1, "b": 2})), text_reply(final_action(0)))
    outcome, _ = _loop_run(handler, [tool])
    assert "add:" not in handler.bodies[0]["messages"][0]["content"]
    result = json.loads(handler.bodies[1]["messages"][-1]["content"].split("\n", 1)[1])
    assert result["error"] == {"type": "unavailable", "message": "ADD_KEY is not set"}
    assert outcome.status == "final"


def test_tool_runs_are_recorded_and_replayed_offline(tmp_path, monkeypatch):
    path = tmp_path / "loop.json"
    bodies = [
        text_reply(tool_action("add", {"a": 17, "b": 25}), prompt=300, completion=30),
        text_reply(final_action({"sum": 42}), prompt=340, completion=12),
    ]

    async def record():
        book = ledger()
        handler = Handler([respond(b) for b in bodies])
        async with _harness(handler, book, cassette=Cassette(path, "record")) as harness:
            outcome = await ToolLoop(harness, [_add_tool()]).run(
                request(model=NANO, messages=_messages())
            )
        return outcome, [e.usd_real for e in book.report("r-1").entries]

    async def replay():
        async def must_not_run(args, ctx):
            raise AssertionError("replay ran the tool")

        book = ledger()
        async with _harness(None, book, cassette=Cassette(path, "replay")) as harness:
            outcome = await ToolLoop(harness, [_add_tool(handler=must_not_run)]).run(
                request(model=NANO, messages=_messages())
            )
        return outcome, [e.usd_real for e in book.report("r-1").entries]

    recorded, recorded_charges = run(record())
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    replayed, replayed_charges = run(replay())
    assert replayed.final == recorded.final == {"sum": 42}
    assert replayed.messages == recorded.messages
    assert replayed_charges == recorded_charges and len(recorded_charges) == 2
    kinds = [i.get("kind", "model") for i in json.loads(path.read_text("utf-8"))["interactions"]]
    assert kinds == ["model", "tool", "model"]
