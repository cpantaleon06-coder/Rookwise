"""Output models of the team's agents, validated by the harness (`validate_final`).

Domain-neutral: a plan is blocks of tasks for operator roles, an operator returns a
summary and claims with citations (`rookwise.evidence`), a manager a block summary, and
the auditor a verdict with its checks. Task and block ids are given by code, not by the
model.

An operator's citation has exactly `source_id`, `line_start`, `line_end` and `quote`, and
the quote must be a single line: a quote with a line break fails validation here, so the
harness asks for a repair (it counts toward the repair limit) instead of the quote
failing later in the evidence check.

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

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rookwise.evidence import Citation, Claim, EvidenceBundle, normalize_whitespace, split_lines


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanTask(_Out):
    role: str
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


_SourceCitation, _FindingClaim, _Findings = SourceCitation, FindingClaim, Findings


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


def findings_model(bundle: EvidenceBundle) -> type[Findings]:
    """`Findings` for one run: same name and JSON Schema, plus the check that each quote
    sits inside a single line of `bundle` in the cited range."""
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

    class Findings(_Findings):
        __doc__ = _Findings.__doc__
        claims: list[FindingClaim] = Field(default_factory=list)

    return Findings


class BlockSummary(_Out):
    summary: str


class AuditPoint(_Out):
    criterion: str
    passed: bool
    note: str = ""


class AuditJudgment(_Out):
    verdict: Literal["accepted", "rejected"]
    checks: list[AuditPoint] = Field(min_length=1)
