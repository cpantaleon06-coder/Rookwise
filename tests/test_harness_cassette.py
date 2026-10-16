"""Record and replay: identical events and ledger charges, misses, ordering, secrets.

tests/cassettes/harness_basic.json is committed. It is recorded from the mock transport
below, so the recording test also proves recording is deterministic. To regenerate it
after an intended change, run pytest with ROOKWISE_REGENERATE_CASSETTES=1.
"""

import json
import os
import random
from contextlib import aclosing
from pathlib import Path

import pytest
from harness_support import (
    TEST_KEY,
    ULTRA,
    FakeClock,
    Handler,
    HangingStream,
    broken_after,
    config,
    content,
    final_usage,
    finish,
    ledger,
    ok_stream,
    reasoning,
    request,
    respond,
    role,
    run,
    sse,
)

from rookwise.harness import (
    ApiError,
    CancelHandle,
    ConfigError,
    ErrorEvent,
    Harness,
    StreamInterrupted,
    TextDelta,
    load_config,
)
from rookwise.harness.cassette import (
    Cassette,
    CassetteMiss,
    CassetteSecretError,
    env_secrets,
    find_secrets,
    request_key,
)

CASSETTES = Path(__file__).resolve().parent / "cassettes"
GOLDEN = CASSETTES / "harness_basic.json"

CALLS = [
    request(),
    request(),  # identical: replays in order through the sequence index
    request(model=ULTRA, reasoning=True, task_id="t-2", max_tokens=256),
    request(task_id="t-3", messages=[{"role": "user", "content": "Bad request."}]),
    request(task_id="t-4", messages=[{"role": "user", "content": "No usage."}]),
]
RESPONSES = [
    respond(ok_stream("1 2 3", prompt=35, completion=21)),
    respond(ok_stream("4 5 6", prompt=35, completion=22)),
    respond(
        sse(
            [
                role(),
                reasoning("3 pens cost $2, so 12 cost $8.", ("reasoning_content",)),
                content("$8"),
                finish(),
                final_usage(prompt=41, completion=99, cached=0, reasoning_tokens=95),
            ]
        )
    ),
    respond(b'{"detail": [{"type": "missing", "loc": ["body", "x"]}]}', 422),
    respond(sse([role(), content("partial"), finish()])),
]


def _harness(book, cassette, handler=None):
    return Harness(
        book,
        config=config(),
        api_key=TEST_KEY if cassette.mode != "replay" else None,
        transport=handler.transport() if handler else None,
        clock=FakeClock(),
        rng=random.Random(0),
        cassette=cassette,
    )


async def _run_calls(harness):
    """Every call's events, or the error kind it raised."""
    outcomes = []
    for call in CALLS:
        events = []
        try:
            async with aclosing(harness.stream(call)) as stream:
                async for event in stream:
                    events.append(event)
        except ApiError as error:
            events.append(("raised", error.kind))
        outcomes.append(events)
    return outcomes


def _charges(book):
    report = book.report("r-1")
    assert report.held_usd == 0
    return [
        (e.task_id, e.model, e.input_tokens, e.output_tokens, e.reasoning_tokens, e.usd_real)
        for e in report.entries
    ]


def _record(path):
    async def main():
        book = ledger()
        handler = Handler(list(RESPONSES))
        async with _harness(book, Cassette(path, "record"), handler) as harness:
            outcomes = await _run_calls(harness)
        return outcomes, _charges(book)

    return run(main())


def _replay(path, monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)

    async def main():
        book = ledger()
        async with _harness(book, Cassette(path, "replay")) as harness:
            assert harness.mode == "replay"
            outcomes = await _run_calls(harness)
        return outcomes, _charges(book)

    return run(main())


def test_recording_matches_the_committed_cassette(tmp_path):
    path = tmp_path / "harness_basic.json"
    _record(path)
    if os.environ.get("ROOKWISE_REGENERATE_CASSETTES") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    assert path.read_text(encoding="utf-8") == GOLDEN.read_text(encoding="utf-8")


def test_replay_gives_identical_events_and_ledger_charges(tmp_path, monkeypatch):
    live_outcomes, live_charges = _record(tmp_path / "c.json")
    replay_outcomes, replay_charges = _replay(GOLDEN, monkeypatch)
    assert replay_outcomes == live_outcomes
    assert replay_charges == live_charges
    texts = ["".join(e.text for e in o if isinstance(e, TextDelta)) for o in replay_outcomes]
    assert texts[:3] == ["1 2 3", "4 5 6", "$8"]
    assert replay_outcomes[3][-1] == ("raised", "validation")
    assert replay_outcomes[4][-1].usage_estimated is True


def test_replay_miss_raises_and_never_calls_the_api(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)

    async def main():
        book = ledger()
        async with _harness(book, Cassette(GOLDEN, "replay")) as harness:
            with pytest.raises(CassetteMiss) as caught:
                await harness.complete(request(messages=[{"role": "user", "content": "new"}]))
            assert "HARNESS_MODE=record" in str(caught.value)
            await harness.complete(request())
            await harness.complete(request())
            with pytest.raises(CassetteMiss) as third:  # only two identical calls recorded
                await harness.complete(request())
            assert third.value.index == 2
            assert third.value.key == request_key(harness_body())
        assert len(_charges(book)) == 2

    def harness_body():
        from rookwise.harness import build_request

        return build_request(request(), config()).body

    run(main())


def test_a_retried_call_replays_its_final_attempt_with_the_same_charge(tmp_path, monkeypatch):
    path = tmp_path / "retry.json"

    async def record():
        book = ledger()
        handler = Handler(
            [respond(b"slow down", 429, {"retry-after": "2"}), respond(ok_stream("ok"))]
        )
        async with _harness(book, Cassette(path, "record"), handler) as harness:
            result = await harness.complete(request())
        assert any(isinstance(e, ErrorEvent) for e in result.events)
        return _charges(book)

    async def replay():
        book = ledger()
        async with _harness(book, Cassette(path, "replay")) as harness:
            result = await harness.complete(request())
        assert result.attempts == 1 and result.text == "ok"
        return _charges(book)

    recorded = run(record())
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    assert run(replay()) == recorded
    assert len(json.loads(path.read_text(encoding="utf-8"))["interactions"]) == 1


def test_cancelled_and_interrupted_calls_replay_the_same_way(tmp_path, monkeypatch):
    path = tmp_path / "cut.json"
    cancelled = request(task_id="t-c")
    broken = request(task_id="t-b", messages=[{"role": "user", "content": "Break."}])

    async def record():
        book = ledger()
        hanging = HangingStream(sse([role(), content("1")], done=False))
        handler = Handler([hanging, broken_after(sse([role(), content("2")], done=False))])
        cancel = CancelHandle()
        async with _harness(book, Cassette(path, "record"), handler) as harness:
            async with aclosing(harness.stream(cancelled, cancel)) as stream:
                async for event in stream:
                    if isinstance(event, TextDelta):
                        cancel.cancel()
            with pytest.raises(StreamInterrupted):
                await harness.complete(broken)
        return _charges(book)

    async def replay():
        book = ledger()
        async with _harness(book, Cassette(path, "replay")) as harness:
            result = await harness.complete(cancelled)  # no cancel this time
            assert result.cancelled and result.text == "1" and result.usage_estimated
            with pytest.raises(StreamInterrupted):
                await harness.complete(broken)
        return _charges(book)

    recorded = run(record())
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    assert run(replay()) == recorded


def test_realtime_replay_waits_out_the_recorded_offsets(tmp_path, monkeypatch):
    path = tmp_path / "slow.json"
    run(_record_one(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["interactions"][0]["events"] = [
        {"type": "text_delta", "text": "a", "t": 0.5},
        {"type": "text_delta", "text": "b", "t": 1.5},
    ]
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)

    async def main():
        clock = FakeClock()
        harness = Harness(
            ledger(), config=config(), clock=clock, cassette=Cassette(path, "replay", realtime=True)
        )
        async with harness:
            result = await harness.complete(request())
        assert result.text == "ab" and clock.sleeps == [0.5, 1.0]

    run(main())


async def _record_one(path):
    handler = Handler([respond(ok_stream("x"))])
    async with _harness(ledger(), Cassette(path, "record"), handler) as harness:
        await harness.complete(request())


def test_key_is_canonical_and_ignores_credentials():
    assert request_key({"b": 1, "a": [1, {"y": 2, "x": 1}]}) == request_key(
        {"a": [1, {"x": 1, "y": 2}], "b": 1}
    )
    assert request_key({"a": 1, "Authorization": "Bearer abc"}) == request_key({"a": 1})
    assert request_key({"a": 1}) != request_key({"a": 2})


def test_a_write_that_would_contain_a_secret_is_refused(tmp_path):
    path = tmp_path / "leak.json"
    cassette = Cassette(path, "record", secrets=[TEST_KEY])
    interaction = {"key": "k", "index": 0, "events": [], "request": {}}
    with pytest.raises(CassetteSecretError) as caught:
        cassette.put({**interaction, "request": {"messages": [{"content": TEST_KEY}]}})
    assert TEST_KEY not in str(caught.value)
    with pytest.raises(CassetteSecretError):
        cassette.put({**interaction, "events": [{"text": "Bearer " + "x" * 20}]})
    assert not path.exists()
    cassette.put({**interaction, "request": {"api_key": "dropped", "model": "m"}})
    assert "dropped" not in path.read_text(encoding="utf-8")


def test_every_cassette_written_by_tests_is_free_of_secrets(tmp_path):
    _record(tmp_path / "scan.json")
    fixtures = CASSETTES.parent / "fixtures" / "cassettes"
    files = (
        sorted(CASSETTES.glob("**/*.json"))
        + sorted(fixtures.glob("**/*.json"))
        + sorted(tmp_path.glob("*.json"))
    )
    assert fixtures / "operator_tool_run.json" in files
    assert GOLDEN in files
    secrets = [TEST_KEY, *env_secrets()]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert find_secrets(text, secrets) == [], path.name
        assert "authorization" not in text.lower(), path.name


def test_mode_and_cassette_dir_come_from_the_environment(tmp_path):
    cfg = load_config(env={"HARNESS_MODE": "replay", "HARNESS_CASSETTE_DIR": str(tmp_path)})
    assert cfg.mode == "replay" and cfg.cassette_dir == tmp_path
    assert load_config(env={}).mode == "live"
    with pytest.raises(ConfigError):
        load_config(env={"HARNESS_MODE": "sometimes"})


def test_tool_call_deltas_are_recorded_and_replayed(tmp_path, monkeypatch):
    from harness_support import tool_call

    path = tmp_path / "tools.json"
    body = sse(
        [
            role(),
            tool_call(id="c1", name="add", arguments='{"a":1}'),
            finish("tool_calls"),
            final_usage(prompt=10, completion=5),
        ]
    )

    async def record():
        async with _harness(ledger(), Cassette(path, "record"), Handler([respond(body)])) as h:
            return await h.complete(request())

    recorded = run(record())
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)

    async def replay():
        async with _harness(ledger(), Cassette(path, "replay")) as h:
            return await h.complete(request())

    replayed = run(replay())
    assert replayed.tool_calls == recorded.tool_calls and len(recorded.tool_calls) == 1
    assert replayed.events == recorded.events
