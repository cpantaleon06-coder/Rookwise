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

An operator reads one slice, so its citations' source is derived from that slice, not
taken from the model: with a `SliceAssignment` (set by the team before each operator call),
the operators' model rewrites a citation's `source_id` to the slice's source when it is
missing or names the same slice in another form (the slice's store reference, with or
without a line range, or "<source>:<range>"), and counts each rewrite. Any other
`source_id`, including another source of the run, fails validation. The quote and line
checks are unchanged.

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

import re
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
    """One citation of one reply: valid on its own, or the problem the schema found.
    `ok` is after the source is derived from the operator's slice; `ok_as_written` is the
    citation exactly as the model wrote it (the same as `ok` where nothing was derived)."""

    claim_index: int
    citation_index: int
    ok: bool
    problem: str = ""
    ok_as_written: bool | None = None

    @property
    def ok_before_normalization(self) -> bool:
        return self.ok if self.ok_as_written is None else self.ok_as_written


@dataclass(frozen=True)
class ReplyCitations:
    """The citations of one validated reply. `index` counts the task's replies, so index
    0 is its first reply, before any repair. `trimmed` counts the citations dropped from
    the reply, before any check, because a claim had more than the cap."""

    task_id: str
    index: int
    citations: tuple[CitationCheck, ...]
    trimmed: int = 0
    trimmed_claims: int = 0


@dataclass
class CitationLog:
    """Per-citation results of every reply a run-bound model validates. The team sets
    `task_id` before each call; calls run one after another."""

    task_id: str = ""
    replies: list[ReplyCitations] = field(default_factory=list)

    def record(
        self,
        data: Any,
        citation_model: type[BaseModel],
        as_written: Any = None,
        trimmed: int = 0,
        trimmed_claims: int = 0,
    ) -> None:
        """Check every citation of `data`; with `as_written` (the reply before its
        sources were derived), also check each citation as the model wrote it. `trimmed`
        and `trimmed_claims` are how many citations and claims were dropped from the reply
        over the caps."""
        checks = []
        for i, j, citation in _citations(data):
            original = _citation_at(as_written, i, j) if as_written is not None else None
            ok_as_written = None
            if original is not None and original != citation:
                ok_as_written = _valid(citation_model, original)[0]
            ok, problem = _valid(citation_model, citation)
            checks.append(CitationCheck(i, j, ok, problem, ok_as_written))
        index = sum(reply.task_id == self.task_id for reply in self.replies)
        self.replies.append(
            ReplyCitations(self.task_id, index, tuple(checks), trimmed, trimmed_claims)
        )

    def first_replies(self) -> list[ReplyCitations]:
        return [reply for reply in self.replies if reply.index == 0]

    def trimmed_by_task(self) -> dict[str, int]:
        """Citations trimmed over the cap, by task id, over every reply."""
        trimmed: dict[str, int] = {}
        for reply in self.replies:
            if reply.trimmed:
                trimmed[reply.task_id] = trimmed.get(reply.task_id, 0) + reply.trimmed
        return trimmed


def dedupe_plan(plan: Plan) -> tuple[Plan, int]:
    """`plan` without the tasks that repeat the (role, source_id) of an earlier task, in
    any block, and without the blocks that leaves empty; and how many tasks were dropped.
    The first task of each pair stays, so every source the plan read is still read."""
    seen: set[tuple[str, str]] = set()
    blocks = []
    dropped = 0
    for block in plan.blocks:
        kept = []
        for task in block.tasks:
            pair = (task.role, task.source_id)
            if pair in seen:
                dropped += 1
                continue
            seen.add(pair)
            kept.append(task)
        if kept:
            blocks.append(block.model_copy(update={"tasks": kept}))
    if not dropped:
        return plan, 0
    return plan.model_copy(update={"blocks": blocks}), dropped


def hoist_notes(value: Any) -> tuple[Any, bool]:
    """A final result `{"status", "output", "notes"}` whose `output` holds a `notes` field,
    with that field moved to the envelope's `notes`, and whether it moved. Nothing else
    moves. When both are non-empty strings they are joined, the envelope's first, on a
    new line; a non-string `output.notes` beside non-empty envelope notes is left in
    place for validation to report."""
    if not isinstance(value, dict):
        return value, False
    output = value.get("output")
    if not isinstance(output, dict) or "notes" not in output:
        return value, False
    inner, outer = output["notes"], value.get("notes", "")
    if outer in ("", None):
        notes = inner
    elif inner in ("", None):
        notes = outer
    elif isinstance(inner, str) and isinstance(outer, str):
        notes = f"{outer}\n{inner}"
    else:
        return value, False
    rest = {k: v for k, v in output.items() if k != "notes"}
    return {**value, "output": rest, "notes": "" if notes is None else notes}, True


def trim_citations(data: Any, cap: int | None) -> tuple[Any, int]:
    """A copy of a reply's output where each claim keeps its first `cap` citations, by
    position, and how many were dropped. Nothing is checked first: which citations stay
    never depends on whether they are valid. `data` is returned as is when nothing is over
    the cap (or `cap` is None)."""
    claims = data.get("claims") if isinstance(data, dict) else None
    if cap is None or not isinstance(claims, list):
        return data, 0
    dropped = 0
    new_claims = []
    for claim in claims:
        citations = claim.get("citations") if isinstance(claim, dict) else None
        if isinstance(citations, list) and len(citations) > cap:
            dropped += len(citations) - cap
            claim = {**claim, "citations": citations[:cap]}
        new_claims.append(claim)
    if not dropped:
        return data, 0
    return {**data, "claims": new_claims}, dropped


def trim_claims(data: Any, cap: int | None) -> tuple[Any, int]:
    """A copy of a diagnosis where only its first `cap` claims stay, by position, and how
    many were dropped. `root_cause_claim_ids` loses the ids of dropped claims (when that
    leaves none, validation asks for a repair, as for any diagnosis without root-cause
    claims). Nothing is checked first. `data` is returned as is when nothing is over."""
    claims = data.get("claims") if isinstance(data, dict) else None
    if cap is None or not isinstance(claims, list) or len(claims) <= cap:
        return data, 0
    kept = claims[:cap]
    trimmed = {**data, "claims": kept}
    root = data.get("root_cause_claim_ids")
    if isinstance(root, list):
        ids = {c.get("claim_id") for c in kept if isinstance(c, dict)}
        trimmed["root_cause_claim_ids"] = [i for i in root if i in ids]
    return trimmed, len(claims) - cap


def _citations(data: Any) -> list[tuple[int, int, Any]]:
    found = []
    claims = data.get("claims") if isinstance(data, dict) else None
    for i, claim in enumerate(claims if isinstance(claims, list) else []):
        citations = claim.get("citations") if isinstance(claim, dict) else None
        for j, citation in enumerate(citations if isinstance(citations, list) else []):
            found.append((i, j, citation))
    return found


def _citation_at(data: Any, i: int, j: int) -> Any:
    return next((c for a, b, c in _citations(data) if (a, b) == (i, j)), None)


def _valid(citation_model: type[BaseModel], citation: Any) -> tuple[bool, str]:
    try:
        citation_model.model_validate(citation)
    except ValidationError as failure:
        return False, "; ".join(error["msg"] for error in failure.errors())
    return True, ""


@dataclass
class SliceAssignment:
    """The slice of the operator call in progress (`source_id` None between calls). The
    team sets it before each operator call, like `CitationLog.task_id`; calls run one after
    another. `normalized` counts the citations whose `source_id` was derived from it."""

    source_id: str | None = None
    slice_ref: str = ""
    normalized: int = 0
    by_task: dict[str, int] = field(default_factory=dict)
    task_id: str = ""

    def assign(self, task_id: str, source_id: str, slice_ref: str) -> None:
        self.task_id, self.source_id, self.slice_ref = task_id, source_id, slice_ref

    def clear(self) -> None:
        self.task_id, self.source_id, self.slice_ref = "", None, ""

    def names_the_slice(self, value: Any) -> bool:
        """Whether `value` is missing or names the assigned slice's source in a form
        other than its source id."""
        source = self.source_id
        if source is None or value == source:
            return False
        if value is None or (isinstance(value, str) and not value.strip()):
            return True
        if not isinstance(value, str):
            return False
        prefix = self.slice_ref[: self.slice_ref.find("/slices/") + len("/slices/")]
        tail = value[len(prefix) :] if prefix and value.startswith(prefix) else value
        return re.fullmatch(rf"{re.escape(source)}(:\d+(-\d+)?)?", tail.strip()) is not None

    def derive(self, data: Any) -> Any:
        """A copy of a reply's output with each citation that names the slice another way
        given the slice's source id; other citations are left for validation to judge."""
        if self.source_id is None or not isinstance(data, dict):
            return data
        claims = data.get("claims")
        if not isinstance(claims, list):
            return data
        count = 0
        new_claims = []
        for claim in claims:
            citations = claim.get("citations") if isinstance(claim, dict) else None
            if not isinstance(citations, list):
                new_claims.append(claim)
                continue
            new_citations = []
            for citation in citations:
                if isinstance(citation, dict) and self.names_the_slice(citation.get("source_id")):
                    citation = {**citation, "source_id": self.source_id}
                    count += 1
                new_citations.append(citation)
            new_claims.append({**claim, "citations": new_citations})
        self.normalized += count
        self.by_task[self.task_id] = self.by_task.get(self.task_id, 0) + count
        return {**data, "claims": new_claims}


def _bound_claim(
    bundle: EvidenceBundle, assignment: SliceAssignment | None = None
) -> tuple[type[SourceCitation], type[FindingClaim]]:
    """`SourceCitation` and `FindingClaim` whose citations check that each quote sits
    inside a single line of `bundle` in the cited range (same names and JSON Schema). With
    an active `assignment`, a citation of any source but the assigned slice's fails."""
    lines = {source_id: split_lines(text) for source_id, text in bundle.sources.items()}

    class SourceCitation(_SourceCitation):
        __doc__ = _SourceCitation.__doc__

        @model_validator(mode="after")
        def _inside_one_line(self) -> SourceCitation:
            source = assignment.source_id if assignment is not None else None
            if source is not None and self.source_id != source:
                raise ValueError(
                    f"source_id {self.source_id!r} is not the slice you were given: cite "
                    f"its lines with source_id {source!r}"
                )
            problem = quote_problem(lines.get(self.source_id), self)
            if problem is not None:
                raise ValueError(problem)
            return self

    class FindingClaim(_FindingClaim):
        __doc__ = _FindingClaim.__doc__
        citations: list[SourceCitation] = Field(default_factory=list)

    return SourceCitation, FindingClaim


def findings_model(
    bundle: EvidenceBundle,
    log: CitationLog | None = None,
    assignment: SliceAssignment | None = None,
    *,
    max_claims: int | None = None,
    max_citations_per_claim: int | None = None,
) -> type[Findings]:
    """`Findings` for one run: same name and JSON Schema, plus the check that each quote
    sits inside a single line of `bundle` in the cited range. With `assignment`, each
    citation's source is derived from the operator's slice (see the module docstring).
    `max_claims` and `max_citations_per_claim` (None: no limit) cap a reply. A reply with
    more claims fails validation with a message the repair can act on. A claim with more
    citations keeps its first `max_citations_per_claim` by position, before any check
    (`trim_citations`), so it asks for no repair; the dropped citations are counted in
    `log` (`ReplyCitations.trimmed`). The JSON Schema does not carry the caps, so it stays
    the same as `Findings`."""
    citation, claim = _bound_claim(bundle, assignment)

    class Findings(_Findings):
        __doc__ = _Findings.__doc__
        claims: list[claim] = Field(default_factory=list)  # type: ignore[valid-type]

        @model_validator(mode="after")
        def _within_the_caps(self) -> Findings:
            if max_claims is not None and len(self.claims) > max_claims:
                raise ValueError(
                    f"the reply has {len(self.claims)} claims; report at most {max_claims}, "
                    "the ones that matter most for the task"
                )
            return self

        @model_validator(mode="wrap")
        @classmethod
        def _log_citations(cls, data: Any, handler: Any) -> Any:
            # Trim first, by position, so the checks below never pick which citations stay.
            data, trimmed = trim_citations(data, max_citations_per_claim)
            as_written = data
            if assignment is not None:
                data = assignment.derive(data)
            if log is not None:
                log.record(data, citation, as_written, trimmed)
            return handler(data)

    return Findings


def diagnosis_model(
    bundle: EvidenceBundle,
    log: CitationLog | None = None,
    *,
    max_claims: int | None = None,
    max_citations_per_claim: int | None = None,
) -> type[Diagnosis]:
    """`Diagnosis` for one run: same name and JSON Schema, shape checks only. Each
    citation is logged against `bundle` (the operators' check), but a failing one does not
    reject the reply: D3 withdraws its claim after the deterministic check. A diagnosis
    over `max_claims` or `max_citations_per_claim` keeps its first claims and citations by
    position, before any check (`trim_claims`, `trim_citations`), with no repair; the
    dropped items are counted in `log`."""
    citation, _ = _bound_claim(bundle)

    class Diagnosis(_Diagnosis):
        __doc__ = _Diagnosis.__doc__

        @model_validator(mode="wrap")
        @classmethod
        def _log_citations(cls, data: Any, handler: Any) -> Any:
            # Trim first, by position, so no check picks which claims or citations stay.
            data, claims = trim_claims(data, max_claims)
            data, citations = trim_citations(data, max_citations_per_claim)
            if log is not None:
                log.record(data, citation, trimmed=citations, trimmed_claims=claims)
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
