"""Every retry attempt in calls.json (`attempt_log`) and its sums in report.json
(`retries`). scripts/run_incident.py on the synthetic bundle of test_run_incident.py,
the stub transport and a fake clock. No network, no live call."""

import asyncio
import random

import httpx
import pytest
from harness_support import FakeClock
from test_run_incident import BUNDLE, FAKE_KEY, TRUTH, _estimate, module  # noqa: F401

from rookwise.harness import ErrorEvent

JITTER = 0.2


def _overloaded_first(inner: httpx.MockTransport, statuses: list[int]) -> httpx.MockTransport:
    """The stub transport, answering the first requests with these error statuses."""
    left = list(statuses)

    def handle(request: httpx.Request) -> httpx.Response:
        if left:
            return httpx.Response(left.pop(0), content=b'{"detail": "overloaded"}')
        return inner.handler(request)

    return httpx.MockTransport(handle)


def _record(module, tmp_path, monkeypatch, statuses):  # noqa: F811
    monkeypatch.setattr(module, "RECORDED_RUN", tmp_path / "none.json")
    monkeypatch.setenv("NEBIUS_API_KEY", FAKE_KEY)
    clock = FakeClock()
    real = module.Harness

    def harness(*args, **kwargs):
        return real(*args, clock=clock, rng=random.Random(0), **kwargs)

    monkeypatch.setattr(module, "Harness", harness)
    config = module.load_config(env={})
    sizes = module.stub_output_tokens()["tokens"]
    inner = module.stub_transport(BUNDLE, ["ticket.md", "runbook.md"], sizes, config)
    report, _, calls = asyncio.run(
        module.run(
            "record",
            "inc-test",
            bundle=BUNDLE,
            truth=TRUTH,
            run_usd="0.50",
            cassette=tmp_path / "incident.json",
            transport=_overloaded_first(inner, statuses),
        )
    )
    return report, calls, clock


def test_every_attempt_of_a_retried_call_is_in_calls_json(module, tmp_path, monkeypatch):  # noqa: F811
    report, calls, clock = _record(module, tmp_path, monkeypatch, [529, 503])
    first, *rest = calls
    log = first["attempt_log"]
    assert [(e["attempt"], e["status_code"], e["kind"], e["outcome"]) for e in log] == [
        (1, 529, "server", "retried"),
        (2, 503, "server", "retried"),
        (3, 200, None, "ok"),
    ]
    for entry, wait in zip(log, (2.0, 5.0), strict=False):
        assert wait * (1 - JITTER) <= entry["wait_s"] <= wait * (1 + JITTER)
    assert log[-1]["wait_s"] is None
    assert [e["wait_s"] for e in log[:2]] == [round(s, 3) for s in clock.sleeps]
    assert first["attempts"] == 3
    # Every other call went through at once: one attempt, ok.
    assert all(
        [(e["attempt"], e["outcome"]) for e in c["attempt_log"]] == [(1, "ok")] for c in rest
    )
    assert report["retries"] == {
        "retried_attempts": 2,
        "retried_by_status": {"503": 1, "529": 1},
        "wait_s_total": round(sum(e["wait_s"] for e in log[:2]), 3),
        "calls_retried": 1,
        "calls_gave_up": 0,
    }


def test_a_call_that_gives_up_ends_its_log_with_gave_up(module, tmp_path, monkeypatch):  # noqa: F811
    # The director's plan call (Ultra, the top of the ladder) is overloaded five times.
    report, calls, _ = _record(module, tmp_path, monkeypatch, [529] * 5)
    log = calls[0]["attempt_log"]
    assert [e["outcome"] for e in log] == ["retried"] * 4 + ["gave_up"]
    assert log[-1]["wait_s"] is None and "raised" in calls[0]
    assert report["retries"]["calls_gave_up"] == 1
    assert report["retries"]["retried_attempts"] == 4


def test_a_refused_reservation_is_logged_as_refused(module, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(module, "RECORDED_RUN", tmp_path / "none.json")
    report, _, calls = _estimate(module, tmp_path, run_usd="0.02")
    refused = [c for c in calls if "raised" in c]
    assert refused
    for call in refused:
        assert call["attempt_log"] == [
            {
                "attempt": 1,
                "status_code": None,
                "kind": "budget",
                "wait_s": None,
                "outcome": "refused",
            }
        ]
    assert report["retries"]["retried_attempts"] == 0


def test_an_estimate_run_logs_one_ok_attempt_per_call(module, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(module, "RECORDED_RUN", tmp_path / "none.json")
    report, _, calls = _estimate(module, tmp_path)
    assert calls and all(
        c["attempt_log"]
        == [{"attempt": 1, "status_code": 200, "kind": None, "wait_s": None, "outcome": "ok"}]
        for c in calls
    )
    assert report["retries"]["calls_retried"] == 0


def test_the_entries_carry_no_error_text(module):  # noqa: F811
    event = ErrorEvent(
        kind="server",
        message="secret prompt echo",
        status_code=529,
        retryable=True,
        attempt=1,
        delay_s=2.123456,
    )
    entry = module.attempt_entry(event)
    assert entry == {
        "attempt": 1,
        "status_code": 529,
        "kind": "server",
        "wait_s": 2.123,
        "outcome": "retried",
    }
    assert "secret" not in str(entry)


@pytest.mark.parametrize(("error", "outcome", "kind"), [(None, "ok", None)])
def test_a_successful_final_attempt(module, error, outcome, kind):  # noqa: F811
    assert module.final_attempt(2, error) == {
        "attempt": 2,
        "status_code": 200,
        "kind": kind,
        "wait_s": None,
        "outcome": outcome,
    }
