"""Output models of the team's agents, validated by the harness (`validate_final`).

Domain-neutral: a plan is blocks of tasks for operator roles, an operator returns a
summary and claims with citations (`rookwise.evidence`), a manager a block summary, and
the auditor a verdict with its checks. Task and block ids are given by code, not by the
model.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rookwise.evidence import Claim


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


class Findings(_Out):
    summary: str
    claims: list[Claim] = Field(default_factory=list)


class BlockSummary(_Out):
    summary: str


class AuditPoint(_Out):
    criterion: str
    passed: bool
    note: str = ""


class AuditJudgment(_Out):
    verdict: Literal["accepted", "rejected"]
    checks: list[AuditPoint] = Field(min_length=1)
