"""Benchmark scoring of a team run's diagnosis. No model, no network.

`score_diagnosis(diagnosis, truth, ...)` applies decision D3 first (`split_claims`: the
diagnosis's unsupported claims are withdrawn) and scores only what is left with
`rookwise.incidents.score`: the diagnosis's category and its supported claims. A
withdrawn claim therefore never counts toward `diagnosis_correct` or `evidence_recall`,
even when one of its citations points at an essential line. It also returns:

- `citation_first_pass_validity`: valid citations over all citations in the first reply
  of every task (index 0 in the run's `CitationLog`), before any repair; None when the
  first replies hold no citation.
- `citation_repairs`: repair attempts spent on citation errors, that is repairs whose
  previous attempt of the same task failed validation on a citation.
- `withdrawn_claims`: how many claims of the diagnosis D3 withdrew.

`score_run(team, truth)` reads all of that from a `TeamRun`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from rookwise.evidence import EvidenceBundle
from rookwise.harness import AttemptRecord
from rookwise.incidents import INCIDENTS_DIR, GroundTruth, Score, load_bundle, score
from rookwise.team.auditor import split_claims
from rookwise.team.flow import TeamRun
from rookwise.team.models import Diagnosis, ReplyCitations

CITATION_ERROR = ".citations."  # in a validation error's location, e.g. output.claims.0.citations.1


@dataclass(frozen=True)
class DiagnosisScore:
    score: Score
    withdrawn_claims: int
    first_pass_citations: int
    first_pass_valid: int
    citation_first_pass_validity: float | None
    citation_repairs: int

    @property
    def diagnosis_correct(self) -> bool:
        return self.score.diagnosis_correct


def first_pass(replies: Sequence[ReplyCitations]) -> tuple[int, int]:
    """(valid, total) citations over every task's first reply."""
    checks = [check for reply in replies if reply.index == 0 for check in reply.citations]
    return sum(check.ok for check in checks), len(checks)


def citation_repairs(attempts: Sequence[AttemptRecord]) -> int:
    """Repairs whose previous attempt of the same task failed on a citation."""
    count = 0
    previous: dict[str, AttemptRecord] = {}
    for attempt in attempts:
        before = previous.get(attempt.task_id)
        if (
            attempt.reason == "repair"
            and before is not None
            and any(CITATION_ERROR in error for error in before.validation_errors)
        ):
            count += 1
        previous[attempt.task_id] = attempt
    return count


def score_diagnosis(
    diagnosis: Diagnosis | None,
    truth: GroundTruth,
    *,
    bundle: EvidenceBundle | None = None,
    citation_log: Sequence[ReplyCitations] = (),
    attempts: Sequence[AttemptRecord] = (),
    root: Path = INCIDENTS_DIR,
) -> DiagnosisScore:
    bundle = bundle if bundle is not None else load_bundle(truth.incident_id, root)
    if diagnosis is None:
        claims, category, withdrawn = [], None, 0
    else:
        split = split_claims(diagnosis, bundle)
        claims = [claim.claim() for claim in split.supported]
        category, withdrawn = diagnosis.category, len(split.withdrawn)
    valid, total = first_pass(citation_log)
    return DiagnosisScore(
        score=score(claims, truth, category=category, bundle=bundle),
        withdrawn_claims=withdrawn,
        first_pass_citations=total,
        first_pass_valid=valid,
        citation_first_pass_validity=valid / total if total else None,
        citation_repairs=citation_repairs(attempts),
    )


def score_run(
    team: TeamRun, truth: GroundTruth, *, bundle: EvidenceBundle | None = None
) -> DiagnosisScore:
    attempts = [e.payload.attempt for e in team.events if e.type == "attempt_recorded"]
    return score_diagnosis(
        team.diagnosis,
        truth,
        bundle=bundle,
        citation_log=team.citation_log,
        attempts=attempts,
    )
