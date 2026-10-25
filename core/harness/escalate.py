"""Repair and escalation around the tool loop, with one record per attempt.

An attempt is one tool-loop run on one model. After it:
- a valid final result with `status: "ok"` ends the call;
- a final result that fails validation gets up to `max_repairs` repair attempts on the
  same model, continuing the conversation with the validation errors;
- anything else (repairs used up, the operator reports `failed`, protocol errors, step
  limit, repeated tool calls, API errors) escalates to the next model in
  `escalation.next` (config/harness.json), starting fresh;
- `length` (a reply cut at its output ceiling, D3), `budget_exhausted`, `token_ceiling`
  and `cancelled` stop at once: the result's `stop_reason` names it, and for `length`,
  `EscalationResult.length` says which ceiling cut the reply. Nothing is retried with
  the same ceiling. The ledger caps still apply to every escalated call: when a
  reservation does not fit, the attempt ends as `budget_exhausted` and nothing more is
  tried.

Every attempt yields an `AttemptRecord`, so the benchmark can report `first_pass_ok`
separately from `ok_after_retry` (a repair on the first model) and
`ok_after_escalation`.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from rookwise.harness.client import CancelHandle
from rookwise.harness.config import EscalationConfig
from rookwise.harness.loop import LengthStop, LoopOutcome, TokenBudget, ToolLoop
from rookwise.harness.request import ChatRequest
from rookwise.harness.validate import Validation, repair_message, validate_final
from rookwise.money import Usd

OutcomeLabel = Literal["first_pass_ok", "ok_after_retry", "ok_after_escalation", "failed"]
AttemptReason = Literal["first", "repair", "escalation"]
# Loop statuses that carry a final result to validate.
FINAL_STATUSES = ("final", "salvaged")
_STOP_AT_ONCE = ("length", "budget_exhausted", "token_ceiling", "cancelled")


class AttemptRecord(BaseModel):
    """One attempt, as the benchmark reads it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    attempt_index: int
    model: str
    protocol: str
    reason: AttemptReason
    retry_reason: str | None
    loop_status: str
    ok: bool
    validation_errors: list[str]
    # Always 0: a `length` finish is never retried, it ends the attempt with loop_status
    # `length`. The field stays for API contract v1.
    length_retries: int
    steps: int
    model_calls: int
    tool_calls: dict[str, int]
    usd: Usd
    input_tokens: int
    output_tokens: int
    usage_estimated: bool
    detail: str = ""


@dataclass
class EscalationResult:
    label: OutcomeLabel
    validation: Validation | None
    attempts: list[AttemptRecord]
    final_model: str
    stop_reason: str | None
    tool_calls: Counter[str] = field(default_factory=Counter)
    length: LengthStop | None = None

    @property
    def ok(self) -> bool:
        return self.label != "failed"


def _failure_reason(outcome: LoopOutcome, validation: Validation) -> str:
    if outcome.status not in FINAL_STATUSES:
        return outcome.status
    if not validation.ok:
        return "validation_failed"
    return "operator_reported_failure"


def _label(attempts: list[AttemptRecord]) -> OutcomeLabel:
    if any(a.reason == "escalation" for a in attempts):
        return "ok_after_escalation"
    if len(attempts) == 1:
        return "first_pass_ok"
    return "ok_after_retry"


async def run_with_escalation(
    loop: ToolLoop,
    request: ChatRequest,
    output_model: type[BaseModel],
    *,
    config: EscalationConfig,
    budget: TokenBudget | None = None,
    cancel: CancelHandle | None = None,
    repair_temperature: float | None = None,
    prepare: Callable[[Any], Any] | None = None,
) -> EscalationResult:
    """`repair_temperature` (None: unchanged) is the loop's sampling from the first
    re-prompt on, in every attempt. `prepare` (None: nothing) turns each final result
    into the value that is validated, before validation."""
    cancel = cancel or CancelHandle()
    attempts: list[AttemptRecord] = []
    tool_calls: Counter[str] = Counter()
    model = request.model
    reason: AttemptReason = "first"
    retry_reason: str | None = None
    history = None
    repairs_left = config.max_repairs
    while True:
        outcome = await loop.run(
            dataclasses.replace(request, model=model),
            history=history,
            budget=budget,
            cancel=cancel,
            repair_temperature=repair_temperature,
        )
        tool_calls += outcome.tool_calls
        if outcome.status in FINAL_STATUSES:
            final = outcome.final if prepare is None else prepare(outcome.final)
            validation = validate_final(final, output_model)
        else:
            detail = f"{outcome.status}: {outcome.detail}" if outcome.detail else outcome.status
            validation = Validation(False, None, (f"(loop): ended with {detail}",))
        ok = validation.operator_ok
        attempts.append(
            AttemptRecord(
                task_id=request.task_id,
                attempt_index=len(attempts),
                model=model,
                protocol=outcome.protocol,
                reason=reason,
                retry_reason=retry_reason,
                loop_status=outcome.status,
                ok=ok,
                validation_errors=list(validation.errors),
                length_retries=0,
                steps=outcome.steps,
                model_calls=outcome.model_calls,
                tool_calls=dict(outcome.tool_calls),
                usd=outcome.usd,
                input_tokens=outcome.input_tokens,
                output_tokens=outcome.output_tokens,
                usage_estimated=outcome.usage_estimated,
                detail=outcome.detail,
            )
        )
        if ok:
            return EscalationResult(_label(attempts), validation, attempts, model, None, tool_calls)
        failure = _failure_reason(outcome, validation)
        if outcome.status in _STOP_AT_ONCE:
            return EscalationResult(
                "failed", validation, attempts, model, outcome.status, tool_calls, outcome.length
            )
        if failure == "validation_failed" and repairs_left > 0:
            repairs_left -= 1
            history = [
                *outcome.messages,
                {
                    "role": "user",
                    "content": repair_message(
                        validation.errors, json_protocol=outcome.protocol == "json_protocol"
                    ),
                },
            ]
            reason, retry_reason = "repair", failure
            continue
        next_model = config.next.get(model)
        if next_model is None:
            return EscalationResult(
                "failed", validation, attempts, model, "top_of_ladder", tool_calls
            )
        model, history, repairs_left = next_model, None, config.max_repairs
        reason, retry_reason = "escalation", failure
