"""Message and ledger contracts from docs/ARCHITECTURE.md ("Messages and shared store").

Field names and shapes follow the examples in that section exactly. Extra fields are
rejected so that a model or a caller cannot slip unchecked data through a contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat, NonNegativeInt

# The levels that make model calls, from the "Levels" table. The administrator layer
# and the harness are code and never appear in the ledger.
Level = Literal["vp", "director", "manager", "operator", "auditor"]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskBudget(_Contract):
    max_input_tokens: NonNegativeInt
    max_output_tokens: NonNegativeInt
    max_usd: NonNegativeFloat


class TaskV1(_Contract):
    """task_v1: manager to operator."""

    task_id: str
    run_id: str
    role: str
    instruction_ref: str
    inputs: list[str]
    budget: TaskBudget
    deadline_s: NonNegativeInt


class ResultUsage(_Contract):
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    usd: NonNegativeFloat


class SelfCheck(_Contract):
    schema_valid: bool
    notes: str


class ResultV1(_Contract):
    """result_v1: operator to manager."""

    task_id: str
    status: str
    output_ref: str
    usage: ResultUsage
    self_check: SelfCheck


class LedgerEntry(_Contract):
    """ledger_entry: one charged model call. `skills` lists the skill ids in its prompt."""

    run_id: str
    level: Level
    task_id: str
    model: str
    input_tokens: NonNegativeInt
    cached_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    reasoning_tokens: NonNegativeInt
    cached_price_fallback: bool
    usd_real: NonNegativeFloat
    usd_predicted: NonNegativeFloat
    ts: datetime
    skills: list[str] = Field(default_factory=list)
