"""run_operator end to end against a fake model and a fake Tavily. No network.

tests/fixtures/cassettes/operator_tool_run.json is a committed recording of one full tool run
(model call, Tavily search, model call). Regenerate it after an intended change with
ROOKWISE_REGENERATE_CASSETTES=1.
"""

import json
import os
import random
from pathlib import Path

import httpx
import pytest
from harness_support import (
    TEST_KEY,
    FakeClock,
    Handler,
    ledger,
    replies,
    run,
    text_reply,
    tool_reply,
)
from operator_stub import (
    INPUT_REF,
    SKILLS_CONFIG,
    SKILLS_DIR,
    StubFindings,
    stub_spec,
    stub_store,
    stub_task,
)

from rookwise.harness import Harness, load_config
from rookwise.harness.cassette import Cassette, env_secrets, find_secrets
from rookwise.runner import result_ref, run_operator
from rookwise.tools import TavilySearch

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "cassettes" / "operator_tool_run.json"
FAKE_TAVILY_KEY = "fake-tavily-key-for-tests"
FINAL = {
    "status": "ok",
    "output": {"answer": "NVIDIA makes the Nemotron models.", "sources": ["https://a.example"]},
    "notes": "",
}


def _tavily(key=FAKE_TAVILY_KEY, calls=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is None:
            raise AssertionError("Tavily must not be called")
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Nemotron",
                        "url": "https://a.example",
                        "content": "NVIDIA Nemotron models.",
                    }
                ]
            },
        )

    return TavilySearch(key, transport=httpx.MockTransport(handler))


def _model_replies():
    return [
        tool_reply(
            [("call_1", "search", '{"query": "Nemotron maker", "max_results": 3}')],
            prompt=600,
            completion=30,
        ),
        text_reply(json.dumps(FINAL), prompt=700, completion=40),
    ]


def _operate(handler, *, book=None, tavily=None, cassette=None, spec=None, task=None, store=None):
    book = book or ledger()
    tavily = tavily or _tavily(calls=[])
    store = store or stub_store()
    replay = cassette is not None and cassette.mode == "replay"

    async def main():
        harness = Harness(
            book,
            config=load_config(env={}),
            api_key=None if replay else TEST_KEY,
            transport=None if handler is None else handler.transport(),
            clock=FakeClock(),
            rng=random.Random(0),
            cassette=cassette,
        )
        async with harness:
            record = await run_operator(
                task or stub_task(),
                spec or stub_spec(),
                harness=harness,
                store=store,
                output_model=StubFindings,
                tools={"tavily_search": tavily.tool()},
                skills_config=SKILLS_CONFIG,
                skills_dir=SKILLS_DIR,
            )
        await tavily.aclose()
        return record

    return run(main()), book, store


def _charges(book):
    report = book.report("r-1")
    assert report.held_usd == 0
    return [
        (e.model, e.input_tokens, e.output_tokens, e.usd_real, e.usage_estimated)
        for e in report.entries
    ]


def test_run_operator_end_to_end_with_a_tool_and_ledger_totals():
    calls = []
    handler = replies(*_model_replies())
    record, book, store = _operate(handler, tavily=_tavily(calls=calls))
    assert record.label == "first_pass_ok" and record.stop_reason is None
    result = record.result
    assert result.status == "ok" and result.self_check.schema_valid
    assert result.output_ref == result_ref(stub_task())
    assert store.get(result.output_ref) == FINAL["output"] == record.output
    entries = book.report("r-1").entries
    assert len(entries) == 2 and {e.task_id for e in entries} == {"t-1"}
    assert all(e.skills == ["stub-notes"] and e.level == "operator" for e in entries)
    assert result.usage.usd == record.usd == pytest.approx(sum(e.usd_real for e in entries))
    assert result.usage.input_tokens == 1300 and result.usage.output_tokens == 70
    assert sum(a.usd for a in record.attempts) == pytest.approx(record.usd)
    assert record.tool_calls == {"search": 1} and calls == [
        {"query": "Nemotron maker", "max_results": 3}
    ]
    assert record.usd_predicted == 0.002 and record.usage_estimated is False
    first = handler.bodies[0]
    system, user = first["messages"]
    assert "## Skill: stub-notes" in system["content"]
    assert "## Final result" in system["content"] and "## Tool protocol" in system["content"]
    assert "Find out which company makes" in user["content"] and INPUT_REF in user["content"]
    assert first["tools"][0]["function"]["name"] == "search"
    assert "temperature" not in first and "top_p" not in first  # D4: server defaults
    _charges(book)


def test_per_operator_sampling_overrides_reach_the_request():
    handler = replies(text_reply(json.dumps(FINAL)))
    _operate(handler, spec=stub_spec(temperature=0.3, top_p=0.9))
    assert handler.bodies[0]["temperature"] == 0.3 and handler.bodies[0]["top_p"] == 0.9


def test_the_task_usd_cap_is_enforced_through_the_ledger():
    handler = Handler([])
    record, book, store = _operate(handler, task=stub_task(max_usd=0.0000001))
    assert record.label == "failed" and record.stop_reason == "budget_exhausted"
    assert record.result.status == "failed" and not record.result.self_check.schema_valid
    assert handler.requests == [] and _charges(book) == []
    assert store.get(record.result.output_ref)["error"] == "budget_exhausted"


def test_a_missing_tavily_key_degrades_cleanly(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    handler = replies(text_reply(json.dumps(FINAL)))
    record, _, _ = _operate(handler, tavily=TavilySearch())
    assert record.label == "first_pass_ok" and record.unavailable_tools == ["search"]
    assert "tools" not in handler.bodies[0]


def test_catalog_mismatches_are_refused():
    for spec, message in (
        (stub_spec(role="coder"), "the task needs"),
        (stub_spec(skills=["prose-style"]), "differ from the skills config"),
        (stub_spec(tools=["tavily_search", "calculator"]), "no tool registered"),
        (stub_spec(output_schema="free_text"), "only task_v1"),
    ):
        with pytest.raises(ValueError, match=message):
            _operate(Handler([]), spec=spec)


def test_a_full_tool_run_replays_from_the_committed_cassette(tmp_path, monkeypatch):
    path = tmp_path / "operator_tool_run.json"
    calls = []
    recorded, book, _ = _operate(
        replies(*_model_replies()),
        tavily=_tavily(calls=calls),
        cassette=Cassette(path, "record"),
    )
    recorded_charges = _charges(book)
    if os.environ.get("ROOKWISE_REGENERATE_CASSETTES") == "1":
        GOLDEN.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    assert path.read_text(encoding="utf-8") == GOLDEN.read_text(encoding="utf-8")

    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    replayed, replay_book, store = _operate(
        None, tavily=_tavily(key="", calls=None), cassette=Cassette(GOLDEN, "replay")
    )
    assert _charges(replay_book) == recorded_charges and len(recorded_charges) == 2
    same = ("result", "output", "label", "attempts", "tool_calls", "usd", "usage_estimated")
    assert replayed.model_dump(include=set(same)) == recorded.model_dump(include=set(same))
    assert replayed.tool_calls == {"search": 1} and len(calls) == 1
    assert store.get(replayed.result.output_ref) == FINAL["output"]
    kinds = [i.get("kind", "model") for i in json.loads(GOLDEN.read_text("utf-8"))["interactions"]]
    assert kinds == ["model", "tool", "model"]
    text = GOLDEN.read_text(encoding="utf-8")
    assert find_secrets(text, [TEST_KEY, FAKE_TAVILY_KEY, *env_secrets()]) == []
