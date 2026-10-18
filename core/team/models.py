"""Output models of the team's agents, validated by the harness (`validate_final`).

Domain-neutral: a plan is blocks of tasks for operator roles, an operator returns a
summary and claims with citations (`rookwise.evidence`), a manager a block summary, and
the auditor a verdict with its checks. Task and block ids are given by code, not by the
model.

An operator's citation has exactly `source_id`, `line_start`, `line_end` and `quote`, and
the quote must be a single line: a quote with a line break fails validation here, so the
harness asks for a repair (it counts toward the repair limit) instead of the quote
failing later in the evidence check. A one-line quote may still span a line range, as
the evidence check joins the cited lines with a space (`rookwise.evidence`, unchanged).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from rookwise.evidence import Citation, Claim


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
            "Text copied exactly from the cited lines, on a single line: no line breaks "
            "and no line-number prefix."
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


class BlockSummary(_Out):
    summary: str


class AuditPoint(_Out):
    criterion: str
    passed: bool
    note: str = ""


class AuditJudgment(_Out):
    verdict: Literal["accepted", "rejected"]
    checks: list[AuditPoint] = Field(min_length=1)
