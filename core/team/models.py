"""Output models of the team's agents, validated by the harness (`validate_final`).

Domain-neutral: a plan is blocks of tasks for operator roles, an operator returns a
summary and claims with citations (`rookwise.evidence`), a manager a block summary, and
the auditor a verdict with its checks. Task and block ids are given by code, not by the
model.

An operator's citation has exactly `source_id`, `line_start`, `line_end` and `quote`, and
the quote must be a single line: a quote with a line break fails validation here, so the
harness asks for a repair (it counts toward the repair limit) instead of the quote
failing later in the evidence check.

A plan task names the source it reads (`source_id`); the flow gives every slice of that
source (`rookwise.slicing`) to its own operator. `plan_model(...)` makes the director's
output model for one run: same name and JSON Schema as `Plan`, plus the checks that every
task names a source of the run and that every non-empty source is read, so the plan
covers every slice. A plan that fails them is repaired like any other validation error.

The director ends the investigation with a `Diagnosis`: the root cause, its category
(the benchmark's enum, `rookwise.incidents.Category`), claims with citations exactly like
an operator's, the ids of the claims that support the root cause, and a remediation plan.
v1 is read-only: the plan is a proposal and nothing in it is executed.
`diagnosis_model(bundle, log)` is its run twin, with the same JSON Schema as `Diagnosis`.
Unlike the operators' model it checks shape only (the schema, including the one-line
quote, the category enum and the claim ids): a quote that is not in its cited line does
not reject the reply. The deterministic check and decision D3 handle it instead (the claim
is withdrawn with its reason code; `rookwise.team.auditor`). The citation log still
records every citation of the director's replies against the run's sources.

Both run-bound models take an optional `CitationLog`. With one, every reply they
validate also records, per citation, whether it passed on its own and why not, under the
task id the team sets before each call. Attempt records keep only the validation error
text, so this log is what tells how many citations of a first reply were valid.

`findings_model(bundle)` makes the operators' output model for one run. It has the same
name and JSON Schema as `Findings`, and it also checks every citation against the run's
sources: the whitespace-normalized quote must be part of ONE source line inside
line_start to line_end, so a quote that needs several lines, or joins lines with a
separator such as " | ", fails validation as a repairable error too. The harness and the
runner are unchanged: the run-bound model is passed as the `output_model` they already
take. The evidence check (`rookwise.evidence`, unchanged) still runs in the audit, and
joins the cited lines with a space.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from rookwise.evidence import Citation, Claim, EvidenceBundle, normalize_whitespace, split_lines
from rookwise.incidents import Category


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanTask(_Out):
    role: str
    source_id: str = Field(
        min_length=1,
        description=(
            "The source this task reads. Every slice of it goes to its own operator with "
            "this task's role and instruction."
        ),
    )
    instruction: str = Field(min_length=1)


class PlanBlock(_Out):
    goal: str = Field(min_length=1)
    tasks: list[PlanTask] = Field(min_length=1)


class Plan(_Out):
    summary: str
    blocks: list[PlanBlock] = Field(min_length=1)


class SourceCitation(_Out):
    """A citation as an agent writes it; `citation()` is the one the evidence check reads."""

    source_id: str = Field(description="The source id, exactly as given.")
    line_start: int = Field(description="The first cited line, as numbered in the source.")
    line_end: int = Field(description="The last cited line; equal to line_start for one line.")
    quote: str = Field(
        min_length=1,
        description=(
            "Text copied verbatim from a single line between line_start and line_end, including "
            "its timestamp: no line breaks, no separator joining lines and no line-number "
            "prefix."
        ),
    )

    @field_validator("quote")
    @classmethod
    def _single_line(cls, quote: str) -> str:
        if "\n" in quote or "\r" in quote:
            raise ValueError(
                "the quote must be a single line; to cite several lines, give one citation "
                "per line with line_start equal to line_end"
            )
        return quote

    def citation(self) -> Citation:
        return Citation(**self.model_dump())


class FindingClaim(_Out):
    claim_id: str
    text: str
    citations: list[SourceCitation] = Field(default_factory=list)

    def claim(self, claim_id: str | None = None) -> Claim:
        """The claim the evidence check reads, under `claim_id` when given."""
        return Claim(
            claim_id=claim_id or self.claim_id,
            text=self.text,
            citations=[c.citation() for c in self.citations],
        )


class Findings(_Out):
    summary: str
    claims: list[FindingClaim] = Field(default_factory=list)


class RemediationStep(_Out):
    """One proposed step. v1 executes nothing; the human approves or rejects the plan."""

    action: str = Field(min_length=1, description="What to do, as one concrete step.")
    why: str = Field(min_length=1, description="How the step addresses the root cause.")
    risk: str = Field(min_length=1, description="What could go wrong if the step is taken.")
    reversible: bool = Field(description="Whether the step can be undone.")


class Diagnosis(_Out):
    """The director's diagnosis of the incident, backed by cited claims."""

    root_cause: str = Field(min_length=1)
    category: Category
    claims: list[FindingClaim] = Field(default_factory=list)
    root_cause_claim_ids: list[str] = Field(
        min_length=1, description="The ids of the claims that support the root cause."
    )
    remediation_plan: list[RemediationStep] = Field(min_length=1)

    @model_validator(mode="after")
    def _claim_ids(self) -> Diagnosis:
        ids = [claim.claim_id for claim in self.claims]
        duplicates = sorted({claim_id for claim_id in ids if ids.count(claim_id) > 1})
        if duplicates:
            raise ValueError(f"claim ids must be unique: {', '.join(duplicates)}")
        unknown = [claim_id for claim_id in self.root_cause_claim_ids if claim_id not in ids]
        if unknown:
            raise ValueError(
                f"root_cause_claim_ids {', '.join(unknown)} are not claim ids of this diagnosis"
            )
        return self


_SourceCitation, _FindingClaim, _Findings = SourceCitation, FindingClaim, Findings
_Diagnosis = Diagnosis
_PlanTask, _PlanBlock, _Plan = PlanTask, PlanBlock, Plan


def plan_model(source_ids: Sequence[str], to_read: Sequence[str]) -> type[Plan]:
    """`Plan` for one run: same name and JSON Schema, plus the checks that every task
    names a source of the run and that every source in `to_read` (the non-empty ones) is
    read by at least one task, so the plan covers every slice of the bundle."""
    known, required = list(source_ids), list(to_read)

    class PlanTask(_PlanTask):
        __doc__ = _PlanTask.__doc__

        @model_validator(mode="after")
        def _known_source(self) -> PlanTask:
            if self.source_id not in known:
                raise ValueError(
                    f"there is no source {self.source_id!r}; use one of: {', '.join(known)}"
                )
            return self

    class PlanBlock(_PlanBlock):
        __doc__ = _PlanBlock.__doc__
        tasks: list[PlanTask] = Field(min_length=1)

    class Plan(_Plan):
        __doc__ = _Plan.__doc__
        blocks: list[PlanBlock] = Field(min_length=1)

        @model_validator(mode="after")
        def _every_source_read(self) -> Plan:
            read = {task.source_id for block in self.blocks for task in block.tasks}
            missing = [source_id for source_id in required if source_id not in read]
            if missing:
                raise ValueError(
                    f"no task reads {', '.join(missing)}; give every source at least one task"
                )
            return self

    return Plan


def quote_problem(lines: list[str] | None, citation: SourceCitation) -> str | None:
    """Why a citation's quote is not part of one source line in its range, or None."""
    if lines is None:
        return f"there is no source {citation.source_id!r}"
    start, end = citation.line_start, citation.line_end
    if not 1 <= start <= end <= len(lines):
        return f"lines {start}-{end} are not within 1-{len(lines)} of {citation.source_id}"
    quote = normalize_whitespace(citation.quote)
    if not quote:
        return "the quote is empty"
    if any(quote in normalize_whitespace(line) for line in lines[start - 1 : end]):
        return None
    joined = " | " in citation.quote
    return (
        ("the quote joins lines with ' | '" if joined else "the quote is not part of one line")
        + f" of {citation.source_id} {start}-{end}; copy one line verbatim, including its "
        "timestamp, and give one citation per line to cite several lines"
    )


@dataclass(frozen=True)
class CitationCheck:
    """One citation of one reply: valid on its own, or the problem the schema found."""

    claim_index: int
    citation_index: int
    ok: bool
    problem: str = ""


@dataclass(frozen=True)
class ReplyCitations:
    """The citations of one validated reply. `index` counts the task's replies, so index
    0 is its first reply, before any repair."""

    task_id: str
    index: int
    citations: tuple[CitationCheck, ...]


@dataclass
class CitationLog:
    """Per-citation results of every reply a run-bound model validates. The team sets
    `task_id` before each call; calls run one after another."""

    task_id: str = ""
    replies: list[ReplyCitations] = field(default_factory=list)

    def record(self, data: Any, citation_model: type[BaseModel]) -> None:
        checks = []
        claims = data.get("claims") if isinstance(data, dict) else None
        for i, claim in enumerate(claims if isinstance(claims, list) else []):
            citations = claim.get("citations") if isinstance(claim, dict) else None
            for j, citation in enumerate(citations if isinstance(citations, list) else []):
                try:
                    citation_model.model_validate(citation)
                except ValidationError as failure:
                    problem = "; ".join(error["msg"] for error in failure.errors())
                    checks.append(CitationCheck(i, j, False, problem))
                else:
                    checks.append(CitationCheck(i, j, True))
        index = sum(reply.task_id == self.task_id for reply in self.replies)
        self.replies.append(ReplyCitations(self.task_id, index, tuple(checks)))

    def first_replies(self) -> list[ReplyCitations]:
        return [reply for reply in self.replies if reply.index == 0]


def _bound_claim(bundle: EvidenceBundle) -> tuple[type[SourceCitation], type[FindingClaim]]:
    """`SourceCitation` and `FindingClaim` whose citations check that each quote sits
    inside a single line of `bundle` in the cited range (same names and JSON Schema)."""
    lines = {source_id: split_lines(text) for source_id, text in bundle.sources.items()}

    class SourceCitation(_SourceCitation):
        __doc__ = _SourceCitation.__doc__

        @model_validator(mode="after")
        def _inside_one_line(self) -> SourceCitation:
            problem = quote_problem(lines.get(self.source_id), self)
            if problem is not None:
                raise ValueError(problem)
            return self

    class FindingClaim(_FindingClaim):
        __doc__ = _FindingClaim.__doc__
        citations: list[SourceCitation] = Field(default_factory=list)

    return SourceCitation, FindingClaim


def findings_model(bundle: EvidenceBundle, log: CitationLog | None = None) -> type[Findings]:
    """`Findings` for one run: same name and JSON Schema, plus the check that each quote
    sits inside a single line of `bundle` in the cited range."""
    citation, claim = _bound_claim(bundle)

    class Findings(_Findings):
        __doc__ = _Findings.__doc__
        claims: list[claim] = Field(default_factory=list)  # type: ignore[valid-type]

        @model_validator(mode="wrap")
        @classmethod
        def _log_citations(cls, data: Any, handler: Any) -> Any:
            if log is not None:
                log.record(data, citation)
            return handler(data)

    return Findings


def diagnosis_model(bundle: EvidenceBundle, log: CitationLog | None = None) -> type[Diagnosis]:
    """`Diagnosis` for one run: same name and JSON Schema, shape checks only. Each
    citation is logged against `bundle` (the operators' check), but a failing one does not
    reject the reply: D3 withdraws its claim after the deterministic check."""
    citation, _ = _bound_claim(bundle)

    class Diagnosis(_Diagnosis):
        __doc__ = _Diagnosis.__doc__

        @model_validator(mode="wrap")
        @classmethod
        def _log_citations(cls, data: Any, handler: Any) -> Any:
            if log is not None:
                log.record(data, citation)
            return handler(data)

    return Diagnosis


class BlockSummary(_Out):
    summary: str


class AuditPoint(_Out):
    criterion: str
    passed: bool
    note: str = ""


class AuditJudgment(_Out):
    verdict: Literal["accepted", "rejected"]
    checks: list[AuditPoint] = Field(min_length=1)
