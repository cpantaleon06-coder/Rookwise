"""The independent auditor: deterministic evidence check first, model judgment second.

1. `rookwise.evidence.verify` checks every claim of the deliverable against the evidence
   bundle. Any unsupported claim rejects the deliverable at once, without a model call:
   a model is never asked to judge text whose quotes do not hold.
2. Only when every claim is supported does the auditor model judge the deliverable
   against the goal, inside the auditor's allocation. If that call cannot run (its
   budget ran out) or fails, the deliverable is accepted with a visible warning that
   only the deterministic check ran.

No correction cycle yet: `correction_cycles` is always 0.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from rookwise.api.models import AgentNode, AuditCheck, AuditVerdict
from rookwise.evidence import Claim, EvidenceBundle, EvidenceReport, split_lines, verify
from rookwise.team.agents import AgentCaller
from rookwise.team.config import RoleSpec
from rookwise.team.models import AuditJudgment

AUDITOR_PROMPT = (
    "You are the independent auditor of a team of AI agents. Judge whether the deliverable "
    "meets the goal and whether its claims are supported by the sources you are given. "
    "Each citation names a source_id, a line_start and a line_end, and quotes those lines "
    "on a single line; the deterministic check has already verified every quote, so judge "
    "whether the quoted lines support the claim. Keep to the required final result format."
)
DETERMINISTIC_CRITERION = "Every claim quotes the lines it cites (deterministic check)"


@dataclass(frozen=True)
class AuditOutcome:
    verdict: AuditVerdict
    evidence: EvidenceReport
    model_reviewed: bool
    budget_exhausted: bool


def render_source(source_id: str, text: str) -> str:
    """A source as agents read it: its id, then each line with its 1-based number."""
    numbered = "\n".join(f"{n}: {line}" for n, line in enumerate(split_lines(text), 1))
    return f"Source {source_id} (cite it by this id and these line numbers):\n{numbered}"


def render_sources(bundle: EvidenceBundle) -> str:
    parts = [render_source(source_id, text) for source_id, text in bundle.sources.items()]
    return "\n\n".join(parts) or "(no sources)"


def _deterministic_check(report: EvidenceReport) -> AuditCheck:
    note = f"{report.citations_verified} of {report.citations_total} citations verified"
    if not report.claims:
        note += "; the deliverable makes no claims"
    unsupported = [c for c in report.claims if not c.supported]
    if unsupported:
        note += "; unsupported: " + ", ".join(f"{c.claim_id} ({c.reason})" for c in unsupported)
    return AuditCheck(criterion=DETERMINISTIC_CRITERION, passed=report.all_supported, note=note)


async def audit(
    caller: AgentCaller,
    agent: AgentNode,
    role: RoleSpec,
    *,
    goal: str,
    deliverable: str,
    claims: Sequence[Claim],
    bundle: EvidenceBundle,
    budget_id: str,
) -> AuditOutcome:
    report = verify(bundle, claims)
    check = _deterministic_check(report)
    if not report.all_supported:
        verdict = AuditVerdict(
            verdict="rejected", model=role.model, checks=[check], correction_cycles=0
        )
        return AuditOutcome(verdict, report, model_reviewed=False, budget_exhausted=False)

    claims_json = json.dumps([c.model_dump() for c in claims], ensure_ascii=False, indent=1)
    user = (
        f"Goal: {goal}\n\nDeliverable:\n{deliverable}\n\nClaims with their citations:\n"
        f"{claims_json}\n\nSources:\n{render_sources(bundle)}\n\nDeterministic check: "
        f"{check.note}. Judge the deliverable."
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
    if result.ok and result.validation is not None:
        judgment: AuditJudgment = result.validation.payload.output  # type: ignore[attr-defined]
        checks = [check, *(AuditCheck(**point.model_dump()) for point in judgment.checks)]
        verdict = AuditVerdict(
            verdict=judgment.verdict, model=result.final_model, checks=checks, correction_cycles=0
        )
        return AuditOutcome(verdict, report, model_reviewed=True, budget_exhausted=False)
    exhausted = result.stop_reason == "budget_exhausted"
    warning = (
        "The auditor's budget ran out before its model review; only the deterministic check ran."
        if exhausted
        else f"The auditor's model review failed ({result.stop_reason}); only the "
        "deterministic check ran."
    )
    verdict = AuditVerdict(
        verdict="accepted_with_warning",
        model=result.final_model,
        checks=[check],
        correction_cycles=0,
        warning=warning,
    )
    return AuditOutcome(verdict, report, model_reviewed=False, budget_exhausted=exhausted)
