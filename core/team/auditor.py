"""The independent auditor, and decision D3: unsupported claims are withdrawn first.

1. `rookwise.evidence.verify` checks every claim of the director's diagnosis against the
   evidence bundle (`split_claims`). Every unsupported claim moves from the claims to the
   withdrawn claims, with its reason code and the reason of each of its citations. A
   withdrawn claim is never dropped: the result, the audit and the closing message list
   it.
2. The diagnosis is `inconclusive` when there is no diagnosis, when every claim in
   `root_cause_claim_ids` was withdrawn, or when no supported claim remains. The auditor
   then makes no model call, and the audit says inconclusive (as an `audit_result` with
   verdict `rejected`, a failed "conclusive" check and a warning: API contract v1 has no
   inconclusive verdict).
3. Otherwise the diagnosis is `audited`: the auditor model gets the supported claims, the
   withdrawn list with its reasons, its rubric (`AUDIT_RUBRIC`) and the cited lines with
   a little context, inside the auditor's allocation. When claims were withdrawn, an
   accepted diagnosis is `accepted_with_warning`. If the call cannot run (its budget ran
   out) or fails, the diagnosis is accepted with a warning that only the deterministic
   check ran.

No correction cycle yet: `correction_cycles` is always 0.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from rookwise.api.models import AgentNode, AuditCheck, AuditVerdict
from rookwise.evidence import EvidenceBundle, EvidenceReport, split_lines, verify
from rookwise.slicing import numbered_line
from rookwise.team.agents import AgentCaller
from rookwise.team.config import RoleSpec
from rookwise.team.models import AuditJudgment, Diagnosis, FindingClaim

AUDITOR_PROMPT = (
    "You are the independent auditor of a team of AI agents. Judge whether the deliverable "
    "meets the goal and whether its claims are supported by the sources you are given. "
    "Each citation names a source_id, a line_start and a line_end, and quotes one single "
    "line of that range verbatim, including its timestamp; a claim that rests on several "
    "lines has several citations, and lines are never joined in one quote. The deterministic "
    "check has already verified every quote, so judge whether the quoted lines support the "
    "claim. Keep to the required final result format."
)
DETERMINISTIC_CRITERION = "Every claim quotes the lines it cites (deterministic check)"
CONCLUSIVE_CRITERION = "The diagnosis rests on supported claims (deterministic check)"
AUDIT_RUBRIC = (
    "The root cause follows from the supported claims.",
    "The category matches the root cause.",
    "Each supported claim says only what its cited lines show.",
    "Nothing in the root cause or the remediation plan depends on a withdrawn claim.",
    "Each remediation step addresses the root cause and states its risk and whether it is "
    "reversible.",
)
CONTEXT_LINES = 2  # lines shown around each cited range for the auditor

DiagnosisStatus = Literal["audited", "inconclusive"]


@dataclass(frozen=True)
class WithdrawnClaim:
    """An unsupported claim, kept with its reason code and each citation's reason."""

    claim: FindingClaim
    reason: str
    citation_reasons: tuple[str, ...]


@dataclass(frozen=True)
class ClaimCounts:
    supported: int
    withdrawn: int
    by_reason: Mapping[str, int] = field(default_factory=dict)  # withdrawn, per reason code


@dataclass(frozen=True)
class ClaimSplit:
    supported: tuple[FindingClaim, ...]
    withdrawn: tuple[WithdrawnClaim, ...]
    report: EvidenceReport

    @property
    def counts(self) -> ClaimCounts:
        reasons = Counter(w.reason for w in self.withdrawn)
        return ClaimCounts(len(self.supported), len(self.withdrawn), dict(sorted(reasons.items())))


def split_claims(diagnosis: Diagnosis, bundle: EvidenceBundle) -> ClaimSplit:
    """D3: the diagnosis's supported claims, and the unsupported ones withdrawn with their
    reasons. Every claim lands in exactly one of the two, in its original order."""
    report = verify(bundle, [claim.claim() for claim in diagnosis.claims])
    results = {result.claim_id: result for result in report.claims}
    supported, withdrawn = [], []
    for claim in diagnosis.claims:
        result = results[claim.claim_id]
        if result.supported:
            supported.append(claim)
        else:
            reasons = tuple(c.reason for c in result.citations)
            withdrawn.append(WithdrawnClaim(claim, result.reason, reasons))
    return ClaimSplit(tuple(supported), tuple(withdrawn), report)


@dataclass(frozen=True)
class AuditOutcome:
    verdict: AuditVerdict
    evidence: EvidenceReport | None
    model_reviewed: bool
    budget_exhausted: bool
    status: DiagnosisStatus = "audited"
    supported: tuple[FindingClaim, ...] = ()
    withdrawn: tuple[WithdrawnClaim, ...] = ()
    counts: ClaimCounts = field(default_factory=lambda: ClaimCounts(0, 0))
    reason: str = ""  # why the diagnosis is inconclusive


def render_source(source_id: str, text: str) -> str:
    """A source as agents read it: its id, then each line with its 1-based number."""
    numbered = "\n".join(numbered_line(n, line) for n, line in enumerate(split_lines(text), 1))
    return f"Source {source_id} (cite it by this id and these line numbers):\n{numbered}"


def render_cited_lines(claims: tuple[FindingClaim, ...], bundle: EvidenceBundle) -> str:
    """The lines the supported claims cite, with CONTEXT_LINES around each range, so the
    auditor reads the evidence without the whole bundle."""
    wanted: dict[str, set[int]] = {}
    for claim in claims:
        for citation in claim.citations:
            count = len(split_lines(bundle.sources[citation.source_id]))
            first = max(citation.line_start - CONTEXT_LINES, 1)
            last = min(citation.line_end + CONTEXT_LINES, count)
            wanted.setdefault(citation.source_id, set()).update(range(first, last + 1))
    parts = []
    for source_id, numbers in wanted.items():
        lines = split_lines(bundle.sources[source_id])
        shown, previous = [], None
        for number in sorted(numbers):
            if previous is not None and number != previous + 1:
                shown.append("...")
            shown.append(numbered_line(number, lines[number - 1]))
            previous = number
        parts.append(f"Source {source_id}, cited lines:\n" + "\n".join(shown))
    return "\n\n".join(parts) or "(no cited lines)"


def _deterministic_check(split: ClaimSplit) -> AuditCheck:
    report = split.report
    note = f"{report.citations_verified} of {report.citations_total} citations verified"
    note += f"; {len(split.supported)} claims supported, {len(split.withdrawn)} withdrawn"
    if split.withdrawn:
        note += ": " + ", ".join(f"{w.claim.claim_id} ({w.reason})" for w in split.withdrawn)
    return AuditCheck(criterion=DETERMINISTIC_CRITERION, passed=not split.withdrawn, note=note)


def _inconclusive(
    role: RoleSpec, reason: str, split: ClaimSplit | None, check: AuditCheck | None
) -> AuditOutcome:
    checks = [check] if check is not None else []
    checks.append(AuditCheck(criterion=CONCLUSIVE_CRITERION, passed=False, note=reason))
    verdict = AuditVerdict(
        verdict="rejected",
        model=role.model,
        checks=checks,
        correction_cycles=0,
        warning=f"Inconclusive: {reason}. The auditor made no model call.",
    )
    return AuditOutcome(
        verdict,
        split.report if split else None,
        model_reviewed=False,
        budget_exhausted=False,
        status="inconclusive",
        supported=split.supported if split else (),
        withdrawn=split.withdrawn if split else (),
        counts=split.counts if split else ClaimCounts(0, 0),
        reason=reason,
    )


def _withdrawn_json(withdrawn: tuple[WithdrawnClaim, ...]) -> str:
    items = [
        {
            "claim_id": w.claim.claim_id,
            "text": w.claim.text,
            "reason": w.reason,
            "citation_reasons": list(w.citation_reasons),
        }
        for w in withdrawn
    ]
    return json.dumps(items, ensure_ascii=False, indent=1)


async def audit(
    caller: AgentCaller,
    agent: AgentNode,
    role: RoleSpec,
    *,
    goal: str,
    diagnosis: Diagnosis | None,
    bundle: EvidenceBundle,
    budget_id: str,
    missing_reason: str = "the director produced no diagnosis",
) -> AuditOutcome:
    if diagnosis is None:
        return _inconclusive(role, missing_reason, None, None)
    split = split_claims(diagnosis, bundle)
    check = _deterministic_check(split)
    withdrawn_ids = {w.claim.claim_id for w in split.withdrawn}
    if not split.supported:
        return _inconclusive(role, "no supported claim remains", split, check)
    if all(claim_id in withdrawn_ids for claim_id in diagnosis.root_cause_claim_ids):
        return _inconclusive(role, "every root-cause claim was withdrawn", split, check)

    supported_json = json.dumps(
        [claim.model_dump() for claim in split.supported], ensure_ascii=False, indent=1
    )
    plan_json = json.dumps(
        [step.model_dump() for step in diagnosis.remediation_plan], ensure_ascii=False, indent=1
    )
    rubric = "\n".join(f"- {criterion}" for criterion in AUDIT_RUBRIC)
    root = [c for c in diagnosis.root_cause_claim_ids if c not in withdrawn_ids]
    user = (
        f"Goal: {goal}\n\nDiagnosis:\nRoot cause: {diagnosis.root_cause}\n"
        f"Category: {diagnosis.category}\nRoot-cause claims still supported: "
        f"{', '.join(root)}\n\nSupported claims with their citations:\n{supported_json}\n\n"
        f"Withdrawn claims (unsupported; listed, not part of the diagnosis):\n"
        f"{_withdrawn_json(split.withdrawn) if split.withdrawn else '(none)'}\n\n"
        f"Remediation plan (a proposal; nothing is executed):\n{plan_json}\n\n"
        f"Cited lines:\n{render_cited_lines(split.supported, bundle)}\n\n"
        f"Deterministic check: {check.note}.\n\nRubric, one check per point:\n{rubric}\n\n"
        "Judge the diagnosis."
    )
    result = await caller.call(
        agent,
        role,
        level="auditor",
        task_id="audit",
        base_prompt=AUDITOR_PROMPT,
        user=user,
        output_model=AuditJudgment,
        budget_id=budget_id,
    )
    withdrawn_note = (
        f"{len(split.withdrawn)} claims were withdrawn as unsupported and are listed; the "
        "audit covers the supported rest."
        if split.withdrawn
        else None
    )
    common = {
        "status": "audited",
        "supported": split.supported,
        "withdrawn": split.withdrawn,
        "counts": split.counts,
    }
    if result.ok and result.validation is not None:
        judgment: AuditJudgment = result.validation.payload.output  # type: ignore[attr-defined]
        checks = [check, *(AuditCheck(**point.model_dump()) for point in judgment.checks)]
        verdict_name = judgment.verdict
        if verdict_name == "accepted" and split.withdrawn:
            verdict_name = "accepted_with_warning"
        verdict = AuditVerdict(
            verdict=verdict_name,
            model=result.final_model,
            checks=checks,
            correction_cycles=0,
            warning=withdrawn_note,
        )
        return AuditOutcome(
            verdict, split.report, model_reviewed=True, budget_exhausted=False, **common
        )
    exhausted = result.stop_reason == "budget_exhausted"
    warning = (
        "The auditor's budget ran out before its model review; only the deterministic check ran."
        if exhausted
        else f"The auditor's model review failed ({result.stop_reason}); only the "
        "deterministic check ran."
    )
    if withdrawn_note:
        warning += f" {withdrawn_note}"
    verdict = AuditVerdict(
        verdict="accepted_with_warning",
        model=result.final_model,
        checks=[check],
        correction_cycles=0,
        warning=warning,
    )
    return AuditOutcome(
        verdict, split.report, model_reviewed=False, budget_exhausted=exhausted, **common
    )
