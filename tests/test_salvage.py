"""Salvage of cut or broken operator replies: the pure helper, the loop hook and the team,
which uses it for operators only. SYNTHETIC fixtures; stub transport; no network."""

import json
import random

from harness_support import TEST_KEY, FakeClock, config, ledger, replies, request, run, text_reply
from team_stub import (
    GOOD_CLAIM,
    TeamHandler,
    block,
    findings_payload,
    judgment_reply,
    plan_reply,
    run_stub_team,
    summary_reply,
)

from rookwise.harness import Harness, ToolLoop
from rookwise.harness.salvage import salvage_json

# SYNTHETIC: a findings payload with two claims of two citations each.
CITE = [
    {"source_id": "src-a", "line_start": 1, "line_end": 1, "quote": "the widget weighs 12 units."},
    {"source_id": "src-a", "line_start": 2, "line_end": 2, "quote": "the widget is blue."},
]
CLAIMS = [
    {"claim_id": "c1", "text": "[stub] It weighs 12.", "citations": CITE},
    {"claim_id": "c2", "text": "[stub] It is blue.", "citations": CITE},
]
FULL = json.dumps({"status": "ok", "output": {"summary": "[stub]", "claims": CLAIMS}, "notes": ""})


def _has_complete_citations(value):
    claims = value.get("output", {}).get("claims", []) if isinstance(value, dict) else []
    keys = {"source_id", "line_start", "line_end", "quote"}
    return bool(claims) and all(
        set(c) == keys for claim in claims for c in claim.get("citations", [])
    )


def test_a_reply_missing_its_last_closing_characters_is_kept_whole():
    # Everything up to the last quote's closing mark; every bracket after it is missing.
    text = FULL[: FULL.index(', "notes"')].rstrip("]}")
    assert text.endswith('blue."')
    found = salvage_json(text, _has_complete_citations)
    assert found is not None and found.dropped_elements == 0
    assert found.value["output"]["claims"] == CLAIMS


def test_a_reply_cut_mid_citation_drops_only_that_citation():
    cut = FULL[: FULL.rindex('"quote"') + 12]  # inside the last citation's quote
    found = salvage_json(cut, _has_complete_citations)
    assert found is not None and found.dropped_elements == 1
    kept = found.value["output"]["claims"]
    assert [len(c["citations"]) for c in kept] == [2, 1] and kept[1]["citations"][0] == CITE[0]


def test_a_reply_that_cannot_be_salvaged_gives_none():
    assert salvage_json("The answer is 42.", _has_complete_citations) is None
    assert (
        salvage_json('{"status": "ok", "output": {"summary": "[st', _has_complete_citations) is None
    )
    assert salvage_json("", _has_complete_citations) is None


def _loop(handler, salvage):
    async def main():
        harness = Harness(
            ledger(),
            config=config(),
            api_key=TEST_KEY,
            transport=handler.transport(),
            clock=FakeClock(),
            rng=random.Random(0),
        )
        async with harness:
            req = request(model="nemotron-3.5-lightning", max_tokens=64)
            return await ToolLoop(harness, (), salvage=salvage).run(req)

    return run(main())


def _salvage(text):
    return salvage_json(text, _has_complete_citations)


def test_the_loop_salvages_a_broken_reply_and_a_cut_one():
    broken = FULL[:-2]  # the closing characters are missing
    outcome = _loop(replies(text_reply(broken)), _salvage)
    assert outcome.status == "salvaged" and outcome.model_calls == 1
    assert outcome.final["output"]["claims"] == CLAIMS and "salvaged" in outcome.detail
    cut = FULL[: FULL.rindex('"quote"') + 12]
    outcome = _loop(replies(text_reply(cut, reason="length")), _salvage)
    assert outcome.status == "salvaged" and outcome.length is None
    assert [t["kind"] for t in outcome.trace] == ["length", "salvaged"]


def test_without_salvage_the_loop_is_as_before():
    outcome = _loop(replies(text_reply(FULL[:-2]), text_reply(FULL)), None)
    assert outcome.status == "final" and outcome.model_calls == 2  # re-prompted once
    cut = FULL[: FULL.rindex('"quote"') + 12]
    outcome = _loop(replies(text_reply(cut, reason="length")), None)
    assert outcome.status == "length"
    outcome = _loop(replies(text_reply("no json"), text_reply(FULL)), _salvage)
    assert outcome.status == "final" and outcome.model_calls == 2  # nothing to salvage


def _team(operator_replies, director=None):
    handler = TeamHandler(
        director=director or [plan_reply(block(1))],
        operator=operator_replies,
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = run_stub_team(handler, run_usd="0.5")
    return team, handler


def test_a_cut_operator_reply_with_a_complete_claim_is_salvaged():
    payload = findings_payload(GOOD_CLAIM, {**GOOD_CLAIM, "claim_id": "c2"})
    cut = payload[: payload.rindex('"quote"') + 12]  # the second claim's citation is cut
    team, handler = _team([text_reply(cut, reason="length")])
    (task,) = team.blocks[0].tasks
    assert task.status == "ok" and handler.calls["operator"] == 1
    assert [c.claim_id for c in task.findings.claims] == ["c1", "c2"]
    assert task.findings.claims[1].citations == []  # the cut citation was dropped
    assert team.salvaged_replies == {"t-1": [1]}
    statuses = [e.payload.attempt.loop_status for e in team.events if e.type == "attempt_recorded"]
    assert "salvaged" in statuses


def test_a_salvage_without_a_claim_fails_as_before():
    payload = findings_payload(GOOD_CLAIM)
    cut = payload[: payload.index('"claims"') + 14]  # inside the only claim
    team, handler = _team([text_reply(cut, reason="length"), text_reply(cut, reason="length")])
    (task,) = team.blocks[0].tasks
    assert task.status == "failed" and team.salvaged_replies == {}


def test_the_director_is_never_salvaged():
    plan = json.loads(plan_reply_text())
    broken = json.dumps(plan)[:-2]  # the plan's last closing characters are missing
    team, handler = _team(
        [text_reply(findings_payload(GOOD_CLAIM))],
        director=[text_reply(broken), plan_reply(block(1))],
    )
    assert handler.calls["director"] == 2  # re-prompted, not salvaged
    assert team.salvaged_replies == {}


def plan_reply_text():
    task = {"role": "stub-operator", "source_id": "src-a", "instruction": "[stub] Read."}
    plan = {"summary": "[stub] A plan.", "blocks": [{"goal": "[stub] g", "tasks": [task]}]}
    return json.dumps({"status": "ok", "output": plan, "notes": ""})
