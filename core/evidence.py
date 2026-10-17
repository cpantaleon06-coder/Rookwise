"""Deterministic evidence verification: does each citation quote its source?

No model calls, no network. The auditor runs this before any model-based judgment.

Inputs:
- an `EvidenceBundle`: source_id -> text. A source is read as lines numbered from 1;
  lines end at "\\n", "\\r\\n" or "\\r", and a final line break does not start an extra
  empty line.
- `Claim`s, each with zero or more `Citation`s (source_id, line_start, line_end, quote).

A citation is valid only when, checked in this order:
1. the source exists, else `source_missing`;
2. 1 <= line_start <= line_end <= the number of lines, else `line_out_of_range`;
3. the quote, after whitespace normalization, is a substring of the cited lines after the
   same normalization, else `quote_not_found`. An empty quote is never found.
Whitespace normalization is the only change made to either text: every run of
whitespace (spaces, tabs, line breaks, other Unicode spaces) becomes one space, and the
ends are trimmed. Nothing else: no case folding, no punctuation or Unicode
normalization, no fuzzy matching. The cited lines are joined with a space, so a quote
may run across a line break inside the cited range, never past it.

A claim is supported only when it has at least one citation and every one of its
citations is valid. A claim with zero citations is unsupported (`no_citations`); a claim
whose citations include an invalid one takes the reason of its first invalid citation.
`citation_verified_rate` is valid citations over all citations, 0.0 when there are none.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CitationReason = Literal["ok", "source_missing", "line_out_of_range", "quote_not_found"]
ClaimReason = Literal[
    "ok", "no_citations", "source_missing", "line_out_of_range", "quote_not_found"
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Citation(_Model):
    """Line numbers are not constrained here, so a bad range from a model is reported as
    `line_out_of_range` instead of failing validation."""

    source_id: str
    line_start: int
    line_end: int
    quote: str


class Claim(_Model):
    claim_id: str
    text: str
    citations: list[Citation] = Field(default_factory=list)


class EvidenceBundle(_Model):
    sources: dict[str, str] = Field(default_factory=dict)

    def lines(self, source_id: str) -> list[str]:
        return split_lines(self.sources[source_id])


class CitationResult(_Model):
    claim_id: str
    index: int
    source_id: str
    line_start: int
    line_end: int
    reason: CitationReason
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.reason == "ok"


class ClaimResult(_Model):
    claim_id: str
    supported: bool
    reason: ClaimReason
    citations: list[CitationResult]


class EvidenceReport(_Model):
    claims: list[ClaimResult]
    citations_total: int
    citations_verified: int
    citation_verified_rate: float
    unsupported_claims: list[str]

    @property
    def all_supported(self) -> bool:
        return not self.unsupported_claims


def split_lines(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized:
        return []
    lines = normalized.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def check_citation(bundle: EvidenceBundle, citation: Citation) -> tuple[CitationReason, str]:
    """The reason code and a short human-readable detail for one citation."""
    if citation.source_id not in bundle.sources:
        return "source_missing", f"no source {citation.source_id!r} in the bundle"
    lines = bundle.lines(citation.source_id)
    start, end = citation.line_start, citation.line_end
    if not 1 <= start <= end <= len(lines):
        return "line_out_of_range", f"lines {start}-{end} are not within 1-{len(lines)}"
    quote = normalize_whitespace(citation.quote)
    if not quote:
        return "quote_not_found", "the quote is empty"
    if quote in normalize_whitespace(" ".join(lines[start - 1 : end])):
        return "ok", ""
    if quote in normalize_whitespace(" ".join(lines)):
        return "quote_not_found", f"the quote is in the source but not in lines {start}-{end}"
    return "quote_not_found", "the quote is not in the source"


def verify(bundle: EvidenceBundle, claims: Iterable[Claim]) -> EvidenceReport:
    claims = list(claims)
    ids = [claim.claim_id for claim in claims]
    duplicates = sorted({claim_id for claim_id in ids if ids.count(claim_id) > 1})
    if duplicates:
        raise ValueError(f"claim ids must be unique: {duplicates}")
    results = [_verify_claim(bundle, claim) for claim in claims]
    citations = [c for r in results for c in r.citations]
    verified = sum(c.ok for c in citations)
    return EvidenceReport(
        claims=results,
        citations_total=len(citations),
        citations_verified=verified,
        citation_verified_rate=verified / len(citations) if citations else 0.0,
        unsupported_claims=[r.claim_id for r in results if not r.supported],
    )


def _verify_claim(bundle: EvidenceBundle, claim: Claim) -> ClaimResult:
    checked = []
    for index, citation in enumerate(claim.citations):
        reason, detail = check_citation(bundle, citation)
        checked.append(
            CitationResult(
                claim_id=claim.claim_id,
                index=index,
                source_id=citation.source_id,
                line_start=citation.line_start,
                line_end=citation.line_end,
                reason=reason,
                detail=detail,
            )
        )
    if not checked:
        return ClaimResult(
            claim_id=claim.claim_id, supported=False, reason="no_citations", citations=[]
        )
    failed = next((c.reason for c in checked if not c.ok), None)
    return ClaimResult(
        claim_id=claim.claim_id,
        supported=failed is None,
        reason=failed or "ok",
        citations=checked,
    )
