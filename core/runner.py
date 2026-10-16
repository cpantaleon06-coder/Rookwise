"""Single operator runner: one task_v1 for one catalog operator. No hierarchy yet.

`run_operator(task, spec, ...)`:
1. checks the operator's catalog entry against the task and the skills config;
2. composes the system prompt (base prompt, then the role's skills, `core/skills`) and
   adds the final-result instructions for the operator's output model;
3. reads the instruction and the inputs from the store;
4. sets the task's USD cap in the ledger (`budget.max_usd`) and passes its token
   ceilings to the tool loop;
5. runs the tool loop with repair and escalation (`rookwise.harness`), which writes
   every model call to the ledger;
6. stores the output at `store://<run_id>/results/<task_id>` and returns result_v1,
   built from the ledger's figures, with the attempt records.

Temperature and top_p stay at the server defaults unless the catalog entry or the
model config sets them (D4).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat

from rookwise.harness.client import CancelHandle, Harness
from rookwise.harness.escalate import AttemptRecord, OutcomeLabel, run_with_escalation
from rookwise.harness.loop import TokenBudget, Tool, ToolLoop
from rookwise.harness.request import ChatRequest
from rookwise.harness.validate import build_result, final_result_instructions
from rookwise.schemas import ResultV1, TaskV1
from rookwise.skills import compose_system_prompt
from rookwise.skills.loader import SKILLS_DIR
from rookwise.store import Store

DEFAULT_BASE_PROMPT = (
    "You are an operator in a team of AI agents. Do exactly the task you are given, use "
    "tools only when they help, and keep to the required final result format."
)


class OperatorSpec(BaseModel):
    """A catalog entry (docs/ARCHITECTURE.md, "Operator catalog"), plus optional per-operator
    sampling and length settings. None keeps the model's config (server defaults)."""

    model_config = ConfigDict(extra="forbid")

    operator_id: str
    role: str
    model: str
    price_per_task_est_usd: NonNegativeFloat
    avg_latency_s: NonNegativeFloat
    reputation: float = Field(ge=0, le=1)
    tools: list[str]
    skills: list[str]
    input_schema: str
    output_schema: str
    temperature: float | None = None
    top_p: float | None = None
    reasoning: bool | None = None
    max_tokens: int | None = None


class OperatorRun(BaseModel):
    """The run record of one operator call."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    result: ResultV1
    output: Any
    label: OutcomeLabel
    attempts: list[AttemptRecord]
    tool_calls: dict[str, int]
    usd: float
    usd_predicted: float
    usage_estimated: bool
    stop_reason: str | None
    unavailable_tools: list[str]


def result_ref(task: TaskV1) -> str:
    return f"store://{task.run_id}/results/{task.task_id}"


def _render_input(ref: str, value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return f"[{ref}]\n{text}"


async def run_operator(
    task: TaskV1,
    spec: OperatorSpec,
    *,
    harness: Harness,
    store: Store,
    output_model: type[BaseModel],
    tools: Mapping[str, Tool] | None = None,
    base_prompt: str = DEFAULT_BASE_PROMPT,
    skills_config: dict[str, Any] | None = None,
    skills_dir: Path = SKILLS_DIR,
    cancel: CancelHandle | None = None,
) -> OperatorRun:
    tools = tools or {}
    if (spec.input_schema, spec.output_schema) != ("task_v1", "result_v1"):
        raise ValueError(f"{spec.operator_id}: only task_v1 -> result_v1 operators are supported")
    if spec.role != task.role:
        raise ValueError(f"{spec.operator_id} is a {spec.role}, the task needs a {task.role}")
    missing = [name for name in spec.tools if name not in tools]
    if missing:
        raise ValueError(f"{spec.operator_id}: no tool registered for {missing}")
    composed = compose_system_prompt(
        spec.role, base_prompt, config=skills_config, skills_dir=skills_dir
    )
    if list(composed.skill_ids) != spec.skills:
        raise ValueError(
            f"{spec.operator_id}: catalog skills {spec.skills} differ from the skills "
            f"config {list(composed.skill_ids)}"
        )

    instruction = store.get(task.instruction_ref)
    user = f"Task {task.task_id} ({task.role}).\n\n{instruction}"
    if task.inputs:
        user += "\n\nInputs:\n\n" + "\n\n".join(_render_input(r, store.get(r)) for r in task.inputs)
    system = f"{composed.text}\n\n{final_result_instructions(output_model)}"
    request = ChatRequest(
        model=spec.model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        run_id=task.run_id,
        level="operator",
        task_id=task.task_id,
        max_tokens=spec.max_tokens,
        reasoning=spec.reasoning,
        temperature=spec.temperature,
        top_p=spec.top_p,
        skills=composed.skill_ids,
    )
    ledger = harness.ledger
    ledger.set_task_cap(task.run_id, task.task_id, task.budget.max_usd)
    operator_tools = [tools[name] for name in spec.tools]
    escalation = await run_with_escalation(
        ToolLoop(harness, operator_tools),
        request,
        output_model,
        config=harness.config.escalation,
        budget=TokenBudget(task.budget.max_input_tokens, task.budget.max_output_tokens),
        cancel=cancel,
    )

    entries = [e for e in ledger.report(task.run_id).entries if e.task_id == task.task_id]
    usd = sum(e.usd_real for e in entries)
    validation = escalation.validation
    payload = validation.payload if validation is not None else None
    output = payload.output.model_dump() if escalation.ok and payload is not None else None
    ref = result_ref(task)
    if escalation.ok:
        store.put(ref, output)
    else:
        errors = list(validation.errors) if validation is not None else []
        store.put(ref, {"error": escalation.stop_reason or "failed", "validation_errors": errors})
    notes = escalation.label
    if escalation.stop_reason:
        notes += f"; stopped: {escalation.stop_reason}"
    if payload is not None and getattr(payload, "notes", ""):
        notes += f"; operator: {payload.notes}"
    result = build_result(
        task,
        status="ok" if escalation.ok else "failed",
        output_ref=ref,
        input_tokens=sum(e.input_tokens for e in entries),
        output_tokens=sum(e.output_tokens for e in entries),
        usd=usd,
        schema_valid=validation is not None and validation.ok,
        notes=notes,
    )
    return OperatorRun(
        result=result,
        output=output,
        label=escalation.label,
        attempts=escalation.attempts,
        tool_calls=dict(escalation.tool_calls),
        usd=usd,
        usd_predicted=spec.price_per_task_est_usd,
        usage_estimated=any(e.usage_estimated for e in entries),
        stop_reason=escalation.stop_reason,
        unavailable_tools=[t.name for t in operator_tools if t.unavailable_reason() is not None],
    )
