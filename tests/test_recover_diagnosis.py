"""tools/recover_diagnosis.py: the replay checks and the sidecar it writes, on SYNTHETIC
objects (the replay itself needs a checkout at a run's commit and its cassette)."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from rookwise.evidence import Citation, Claim, EvidenceBundle, verify
from rookwise.team.models import Diagnosis

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "recover_diagnosis", ROOT / "tools" / "recover_diagnosis.py"
)
recover = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(recover)

BUNDLE = EvidenceBundle(
    sources={"app.log": "SYNTHETIC\npool full host=pay-gw.example.net\nqueue depth 900\n"}
)


def _team():
    diagnosis = Diagnosis.model_validate(
        {
            "root_cause": "[synthetic] The pool filled.",
            "category": "capacity_exhaustion",
            "claims": [
                {
                    "claim_id": "c1",
                    "text": "[synthetic] The pool filled.",
                    "citations": [
                        {
                            "source_id": "app.log",
                            "line_start": 2,
                            "line_end": 2,
                            "quote": "pool full host=pay-gw.example.net",
                        }
                    ],
                },
                {
                    "claim_id": "c2",
                    "text": "[synthetic] The queue was empty.",
                    "citations": [
                        {"source_id": "app.log", "line_start": 3, "line_end": 3, "quote": "empty"}
                    ],
                },
            ],
            "root_cause_claim_ids": ["c1"],
            "remediation_plan": [
                {
                    "action": "[synthetic] Raise the pool size.",
                    "why": "[synthetic] It filled.",
                    "risk": "[synthetic] More memory.",
                    "reversible": True,
                }
            ],
        }
    )
    claims = [
        Claim(
            claim_id=c.claim_id,
            text=c.text,
            citations=[Citation(**s.model_dump()) for s in c.citations],
        )
        for c in diagnosis.claims
    ]
    return SimpleNamespace(
        diagnosis=diagnosis, evidence=verify(BUNDLE, claims), empty_sources=["notes.md"]
    )


def _report():
    return {
        "diagnosis": {
            "category": "capacity_exhaustion",
            "supported_claims": [{"claim_id": "c1", "text": "[synthetic] The pool filled."}],
            "withdrawn_claims": [
                {
                    "claim_id": "c2",
                    "text": "[synthetic] The queue was empty.",
                    "reason": "quote_not_found",
                    "citation_reasons": ["quote_not_found"],
                }
            ],
        }
    }


def test_extract_keeps_the_claim_order_citations_and_checks():
    body = recover.extract(_team())
    assert [c["claim_id"] for c in body["diagnosis"]["claims"]] == ["c1", "c2"]
    assert body["diagnosis"]["claims"][0]["citations"][0]["line_start"] == 2
    assert body["diagnosis"]["root_cause_claim_ids"] == ["c1"]
    assert body["diagnosis"]["remediation_plan"][0]["reversible"] is True
    assert body["evidence"] == [
        {"claim_id": "c1", "supported": True, "reason": "ok", "citation_reasons": ["ok"]},
        {
            "claim_id": "c2",
            "supported": False,
            "reason": "quote_not_found",
            "citation_reasons": ["quote_not_found"],
        },
    ]
    assert body["empty_sources"] == ["notes.md"]
    assert recover.check_against_report(body, _report()) == []


def test_a_sidecar_that_disagrees_with_the_report_is_refused():
    body = recover.extract(_team())
    report = _report()
    report["diagnosis"]["withdrawn_claims"][0]["citation_reasons"] = ["ok"]
    assert recover.check_against_report(body, report) == [
        "claim c2 reasons differ from report.json"
    ]
    report = _report()
    report["diagnosis"]["supported_claims"][0]["text"] = "[synthetic] Something else."
    assert "claim c1 text differs from report.json" in recover.check_against_report(body, report)


def test_events_compare_without_timestamps_and_mode():
    recorded = [
        {
            "id": "run_x:1",
            "type": "run_started",
            "mode": "live",
            "ts": "2026-10-25T00:00:00Z",
            "payload": {"mode": "live", "goal": "g"},
        },
        {
            "id": "run_x:2",
            "type": "budget_update",
            "mode": "live",
            "ts": "2026-10-25T00:00:01Z",
            "payload": {"spent_usd": "0.000100", "entry": {"ts": "2026-10-25T00:00:01Z"}},
        },
    ]
    replayed = copy.deepcopy(recorded)
    for event in replayed:
        event["mode"], event["ts"] = "recorded", "2026-10-26T09:00:00Z"
    replayed[0]["payload"]["mode"] = "recorded"
    replayed[1]["payload"]["entry"]["ts"] = "2026-10-26T09:00:01Z"
    assert recover.compare_events(replayed, recorded) == []
    replayed[1]["payload"]["spent_usd"] = "0.000200"
    assert recover.compare_events(replayed, recorded) == ["event run_x:2 (budget_update) differs"]
    assert recover.compare_events(replayed[:1], recorded)[0] == "1 events replayed, 2 recorded"


def test_reports_compare_on_the_run_outcome_only():
    recorded = {
        "status": "finished",
        "partial": False,
        "spent_usd": "0.1",
        "predicted_usd": "0.2",
        "diagnosis": {"category": "x"},
        "audit": None,
        "score": {"a": 1},
        "wall_clock_s": 712.2,
    }
    assert recover.compare_reports({**recorded, "wall_clock_s": 7.1}, recorded) == []
    assert recover.compare_reports({**recorded, "spent_usd": "0.3"}, recorded) == [
        "report spent_usd differs"
    ]


def test_extract_refuses_an_evidence_check_out_of_order():
    team = _team()
    team.evidence = team.evidence.model_copy(
        update={"claims": list(reversed(team.evidence.claims))}
    )
    with pytest.raises(recover.RecoverError, match="in order"):
        recover.extract(team)
