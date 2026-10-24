"""Provider overload (HTTP 529 and other 5xx): a longer, configurable backoff before the
call gives up and the escalation ladder moves it to a larger model. Stub transport and a
fake clock; no network."""

import dataclasses
import json
import random

import pytest
from harness_support import (
    TEST_KEY,
    FakeClock,
    Handler,
    config,
    final_action,
    ledger,
    request,
    respond,
    run,
    text_reply,
)
from pydantic import BaseModel, ConfigDict

from rookwise.harness import ApiError, ConfigError, Harness, ToolLoop
from rookwise.harness.config import REPO_ROOT, load_config
from rookwise.harness.escalate import run_with_escalation
from rookwise.harness.events import ErrorEvent
from rookwise.harness.retry import RetryPolicy

LIGHTNING = "nemotron-3.5-lightning"
NANO = "nemotron-3-nano"  # json_protocol, so a scripted final action ends its loop
SUPER = "nemotron-3-super"
JITTER = 0.2


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sum: int


OK = {"status": "ok", "output": {"sum": 42}, "notes": ""}


def _ok():
    """A final result for a json_protocol model (Nano)."""
    return text_reply(final_action(OK))


def _ok_native():
    """A final result for a native_tools model (Lightning, Super): the plain JSON."""
    return text_reply(json.dumps(OK))


def _overloaded(status=529):
    return respond(b'{"detail": "overloaded"}', status)


def _within_jitter(sleeps, waits):
    assert len(sleeps) == len(waits)
    for slept, wait in zip(sleeps, waits, strict=True):
        assert wait * (1 - JITTER) <= slept <= wait * (1 + JITTER), (slept, wait)


def _complete(handler, clock, cfg=None):
    book = ledger()

    async def main():
        harness = Harness(
            book,
            config=cfg or config(),
            api_key=TEST_KEY,
            transport=handler.transport(),
            clock=clock,
            rng=random.Random(0),
        )
        async with harness:
            return await harness.complete(request(model=LIGHTNING))

    return run(main()), book


def _escalate(handler, clock):
    book = ledger()
    cfg = config()

    async def main():
        harness = Harness(
            book,
            config=cfg,
            api_key=TEST_KEY,
            transport=handler.transport(),
            clock=clock,
            rng=random.Random(0),
        )
        async with harness:
            req = request(
                model=NANO,
                max_tokens=64,
                messages=[
                    {"role": "system", "content": "Test operator."},
                    {"role": "user", "content": "17 + 25?"},
                ],
            )
            return await run_with_escalation(ToolLoop(harness), req, Answer, config=cfg.escalation)

    result = run(main())
    assert book.report("r-1").held_usd == 0
    return result, book


def test_the_overload_schedule_is_config():
    retry = config().retry
    assert retry.overload_max_attempts == 5
    assert retry.overload_delays_s == (2.0, 5.0, 15.0, 30.0)
    assert retry.max_attempts == 4  # other retryable errors keep the general policy


def test_529_waits_on_the_overload_schedule_then_gives_up():
    clock = FakeClock()
    handler = Handler([_overloaded() for _ in range(5)])
    with pytest.raises(ApiError) as caught:
        _complete(handler, clock)
    assert caught.value.kind == "server" and caught.value.status_code == 529
    assert len(handler.requests) == 5
    _within_jitter(clock.sleeps, [2.0, 5.0, 15.0, 30.0])


def test_a_529_that_clears_within_the_schedule_is_charged_once():
    clock = FakeClock()
    handler = Handler([_overloaded(), _overloaded(503), _overloaded(), respond(_ok())])
    (result, book) = _complete(handler, clock)
    assert result.attempts == 4 and len(handler.requests) == 4
    _within_jitter(clock.sleeps, [2.0, 5.0, 15.0])
    errors = [e for e in result.events if isinstance(e, ErrorEvent)]
    assert [(e.status_code, e.retryable) for e in errors] == [(529, True), (503, True), (529, True)]
    (entry,) = book.report("r-1").entries  # failed attempts are released, not charged
    assert entry.usd_real == result.usd


def test_other_retryable_errors_keep_the_general_backoff():
    clock = FakeClock()
    handler = Handler([respond(b"slow", 429) for _ in range(4)])
    with pytest.raises(ApiError) as caught:
        _complete(handler, clock)
    assert caught.value.kind == "rate_limited" and len(handler.requests) == 4
    _within_jitter(clock.sleeps, [1.0, 2.0, 4.0])


def test_retry_after_still_replaces_the_overload_wait():
    clock = FakeClock()
    handler = Handler([respond(b"busy", 529, {"retry-after": "9"}), respond(_ok())])
    _complete(handler, clock)
    assert clock.sleeps == [9.0]


def test_four_overloads_no_longer_escalate_to_the_larger_model():
    # Under the old policy (4 attempts) these four 529s ended the first attempt and the
    # ladder moved the call to Super.
    clock = FakeClock()
    handler = Handler([*[_overloaded() for _ in range(4)], respond(_ok())])
    result, book = _escalate(handler, clock)
    assert result.ok and [a.model for a in result.attempts] == [NANO]
    assert {e.model for e in book.report("r-1").entries} == {NANO}
    _within_jitter(clock.sleeps, [2.0, 5.0, 15.0, 30.0])


def test_the_ladder_escalates_only_after_the_whole_schedule():
    clock = FakeClock()
    handler = Handler([*[_overloaded() for _ in range(5)], respond(_ok_native())])
    result, book = _escalate(handler, clock)
    assert result.ok and [a.model for a in result.attempts] == [NANO, SUPER]
    assert result.attempts[0].loop_status == "api_error"
    assert (
        json.loads(handler.requests[-1].content)["model"]
        != json.loads(handler.requests[0].content)["model"]
    )
    _within_jitter(clock.sleeps, [2.0, 5.0, 15.0, 30.0])


def test_without_an_overload_schedule_server_errors_use_the_general_backoff():
    policy = RetryPolicy(4, base_delay_s=1.0, max_delay_s=30.0, jitter=0.0, max_retry_after_s=60)
    server = ApiError("server", "oops", status_code=529)
    rng = random.Random(0)
    assert [policy.delay(n, server, rng) for n in (1, 2, 3, 4)] == [1.0, 2.0, 4.0, None]
    overload = dataclasses.replace(policy, overload_max_attempts=3, overload_delays_s=(2.0, 5.0))
    assert [overload.delay(n, server, rng) for n in (1, 2, 3)] == [2.0, 5.0, None]


def test_the_overload_config_is_checked(tmp_path):
    data = json.loads((REPO_ROOT / "config" / "harness.json").read_text(encoding="utf-8"))
    data["retry"]["overload"]["delays_s"] = [2.0, 5.0]  # 5 attempts need 4 waits
    path = tmp_path / "harness.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="one delay per retry"):
        load_config(path, env={})
    del data["retry"]["overload"]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_config(path, env={}).retry.overload_delays_s == ()


def test_every_failed_attempt_reaches_the_listener_with_its_wait():
    seen = []
    book = ledger()
    handler = Handler([_overloaded() for _ in range(5)])

    async def main():
        harness = Harness(
            book,
            config=config(),
            api_key=TEST_KEY,
            transport=handler.transport(),
            clock=FakeClock(),
            rng=random.Random(0),
            on_attempt_error=seen.append,
        )
        async with harness:
            await harness.complete(request(model=LIGHTNING))

    with pytest.raises(ApiError):
        run(main())
    assert [(e.attempt, e.status_code, e.retryable) for e in seen] == [
        (1, 529, True),
        (2, 529, True),
        (3, 529, True),
        (4, 529, True),
        (5, 529, False),
    ]
    _within_jitter([e.delay_s for e in seen[:4]], [2.0, 5.0, 15.0, 30.0])
    assert seen[-1].delay_s is None
