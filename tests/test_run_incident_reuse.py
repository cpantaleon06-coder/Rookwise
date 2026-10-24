"""Dev-only cassette reuse in scripts/run_incident.py: a request the old cassette recorded
is served from it at zero cost, a missing one goes to the transport and is recorded into a
new cassette; the old cassette is never modified. The offline dry check, the CLI guards and
the benchmark's refusal. Synthetic bundle and the stub transport; no network."""

import asyncio
import hashlib
import json
from decimal import Decimal

import httpx
import pytest
from test_run_incident import BUNDLE, FAKE_KEY, TRUTH, module  # noqa: F401

from rookwise.harness import Cassette, Harness, HarnessError, load_config
from rookwise.ledger import Caps, InMemoryLedger

COMMON = {"bundle": BUNDLE, "truth": TRUTH, "run_usd": "0.50", "configuration": "c"}


class Counting:
    """The stub transport, counting the requests that reach it, by system prompt start."""

    def __init__(self, module):  # noqa: F811
        config = module.load_config(env={})
        sizes = module.stub_output_tokens()["tokens"]
        self.inner = module.stub_transport(BUNDLE, ["ticket.md", "runbook.md"], sizes, config)
        self.systems = []

    def transport(self):
        def handle(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            self.systems.append(body["messages"][0]["content"][:40])
            return self.inner.handler(request)

        return httpx.MockTransport(handle)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(module, tmp_path, monkeypatch, name, reuse=None, mode="record"):  # noqa: F811
    monkeypatch.setattr(module, "RECORDED_RUN", tmp_path / "none.json")
    monkeypatch.setenv("NEBIUS_API_KEY", FAKE_KEY)
    counting = Counting(module)
    report, events, calls = asyncio.run(
        module.run(
            mode,
            "inc-test",
            cassette=tmp_path / name,
            transport=counting.transport(),
            reuse=reuse,
            **COMMON,
        )
    )
    return report, calls, counting


def _drop_diagnosis(old, new):
    data = json.loads(old.read_text(encoding="utf-8"))
    data["interactions"] = [
        i
        for i in data["interactions"]
        if not i["request"]["messages"][0]["content"].startswith(
            "You are the director of a team of AI agents, and the investigation"
        )
    ]
    new.write_text(json.dumps(data), encoding="utf-8")


def test_a_full_hit_costs_nothing_and_calls_nothing(module, tmp_path, monkeypatch):  # noqa: F811
    first, first_calls, _ = _record(module, tmp_path, monkeypatch, "old.json")
    old = tmp_path / "old.json"
    before = _sha(old)
    report, calls, counting = _record(module, tmp_path, monkeypatch, "new.json", reuse=old)
    assert counting.systems == []  # every request was served from the old cassette
    assert report["replay"] == "partially replayed"
    assert report["reuse"]["misses"] == 0 and report["reuse"]["hits"] == len(first_calls)
    assert report["spent_usd"] == "0.000000" and report["predicted_usd"] == "0.000000"
    assert all(c["reused"] for c in calls)
    assert report["score"] == first["score"]  # the same replies, so the same diagnosis
    assert _sha(old) == before  # the old cassette is only read
    new = json.loads((tmp_path / "new.json").read_text(encoding="utf-8"))
    assert all(i.get("reused") for i in new["interactions"])
    assert all(i["usage"]["input_tokens"] == 0 for i in new["interactions"])


def test_only_the_missing_call_goes_out_and_is_recorded(module, tmp_path, monkeypatch):  # noqa: F811
    _, first_calls, _ = _record(module, tmp_path, monkeypatch, "old.json")
    old, partial = tmp_path / "old.json", tmp_path / "partial.json"
    _drop_diagnosis(old, partial)
    before = _sha(partial)
    report, calls, counting = _record(module, tmp_path, monkeypatch, "new.json", reuse=partial)
    assert len(counting.systems) == 1 and counting.systems[0].startswith("You are the director")
    reuse = report["reuse"]
    assert reuse["misses"] == 1 and reuse["by_role"]["director (diagnosis)"] == {
        "hits": 0,
        "misses": 1,
    }
    assert reuse["hits"] == len(first_calls) - 1
    (miss,) = [c for c in calls if not c["reused"]]
    assert miss["task_id"] == "diagnosis"
    assert report["spent_usd"] == miss["usd"] == reuse["misses_usd"]
    assert _sha(partial) == before
    new = json.loads((tmp_path / "new.json").read_text(encoding="utf-8"))
    assert [i.get("reused", False) for i in new["interactions"]].count(False) == 1
    # The new cassette replays the partial run on its own, offline.
    monkeypatch.delenv("NEBIUS_API_KEY")
    replayed, _, _ = asyncio.run(
        module.run("replay", "inc-test", cassette=tmp_path / "new.json", **COMMON)
    )
    assert replayed["spent_usd"] == report["spent_usd"]
    assert replayed["score"] == report["score"]


def test_the_dry_check_serves_misses_from_the_stub_and_prices_them(module, tmp_path, monkeypatch):  # noqa: F811
    _record(module, tmp_path, monkeypatch, "old.json")
    partial = tmp_path / "partial.json"
    _drop_diagnosis(tmp_path / "old.json", partial)
    monkeypatch.delenv("NEBIUS_API_KEY")
    report, _, _ = asyncio.run(
        module.run(
            "reuse-check", "inc-test", cassette=tmp_path / "check.json", reuse=partial, **COMMON
        )
    )
    reuse = report["reuse"]
    assert reuse["misses"] == 1 and reuse["by_role"]["director (diagnosis)"]["misses"] == 1
    assert float(reuse["misses_predicted_usd"]) > 0
    assert report["replay"] == "partially replayed"


def test_the_cli_dry_check_prints_hits_misses_and_cost(module, tmp_path, monkeypatch, capsys):  # noqa: F811
    _record(module, tmp_path, monkeypatch, "old.json")
    monkeypatch.setattr(module, "load_bundle", lambda _: BUNDLE)
    monkeypatch.setattr(module, "load_ground_truth", lambda _: TRUTH)
    monkeypatch.setattr(module, "OUT_DIR", tmp_path / "out")
    code = module.main(
        [
            "inc-test",
            "reuse-check",
            "--configuration",
            "c",
            "--run-usd",
            "0.30",
            "--reuse-cassette",
            str(tmp_path / "old.json"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "director (diagnosis): 1 hits, 0 misses" in out
    assert "Predicted live cost of the misses: USD 0.000000" in out
    assert not (tmp_path / "out").exists()  # writes nothing


def test_the_cli_guards_reuse(module, tmp_path, monkeypatch, capsys):  # noqa: F811
    old = tmp_path / "old.json"
    old.write_text('{"version": 1, "interactions": []}', encoding="utf-8")
    monkeypatch.setattr(module, "OUT_DIR", tmp_path / "out")
    monkeypatch.setenv("HARNESS_MODE", "record")
    base = [
        "inc-01",
        "record",
        "--configuration",
        "c",
        "--run-usd",
        "0.30",
        "--approve-cap",
        "0.30",
        "--reuse-cassette",
        str(old),
    ]
    cases = [
        (["inc-01", "estimate", "--reuse-cassette", str(old)], "record and reuse-check modes only"),
        (["inc-01", "replay", "--reuse-cassette", str(old)], "record and reuse-check modes only"),
        (base, "needs --cassette"),
        ([*base, "--cassette", str(old)], "must be a new file"),
        (["inc-02", *base[1:], "--cassette", str(tmp_path / "n.json")], "dev only"),
        (["inc-01", "reuse-check"], "needs --reuse-cassette"),
    ]
    for argv, message in cases:
        assert module.main(argv) == 2, argv
        assert message in capsys.readouterr().out
    (tmp_path / "out" / "inc-01" / "record-c.new").mkdir(parents=True)
    assert module.main([*base, "--cassette", str(tmp_path / "new.json")]) == 2
    assert "a report folder is never overwritten" in capsys.readouterr().out


def test_the_harness_reads_a_reuse_cassette_only_while_recording(tmp_path):
    ledger = InMemoryLedger()
    ledger.open_run("r", Caps(run_usd=Decimal("1")))
    old = tmp_path / "old.json"
    old.write_text('{"version": 1, "interactions": []}', encoding="utf-8")
    reuse = Cassette(old, "replay")
    with pytest.raises(HarnessError, match="replay mode by a record harness"):
        Harness(ledger, config=load_config(env={}), api_key="k", reuse=reuse)
    with pytest.raises(HarnessError, match="must not be the cassette being recorded"):
        Harness(
            ledger,
            config=load_config(env={}),
            api_key="k",
            cassette=Cassette(old, "record"),
            reuse=reuse,
        )


def test_the_benchmark_refuses_reuse(capsys):
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "run_benchmark.py"
    spec = importlib.util.spec_from_file_location("run_benchmark_reuse", path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules["run_benchmark_reuse"] = loaded
    spec.loader.exec_module(loaded)
    assert loaded.main(["--reuse-cassette", "x.json"]) == 2
    assert "--reuse-cassette is refused" in capsys.readouterr().out
