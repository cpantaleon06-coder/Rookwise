"""Validation of an operator's final answer, and the result_v1 built from it.

The model never writes result_v1 itself: usage and references are the harness's facts,
not the model's. The model's final result is a payload

    {"status": "ok" | "failed", "output": <the operator's output model>, "notes": "..."}

validated with pydantic against the operator's output model. The runner then builds
result_v1 (task_id, output_ref, usage from the ledger, self_check) and validates that
against `rookwise.schemas.ResultV1`. Errors are plain strings, so they can be fed back
to the model in a repair attempt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, create_model

from rookwise.schemas import ResultUsage, ResultV1, SelfCheck, TaskV1


@dataclass(frozen=True)
class Validation:
    ok: bool
    payload: BaseModel | None
    errors: tuple[str, ...]

    @property
    def operator_ok(self) -> bool:
        """Valid, and the operator says it completed the task."""
        return self.ok and getattr(self.payload, "status", None) == "ok"


def payload_model(output_model: type[BaseModel]) -> type[BaseModel]:
    return create_model(
        f"{output_model.__name__}Payload",
        __config__=ConfigDict(extra="forbid"),
        status=(Literal["ok", "failed"], ...),
        output=(output_model, ...),
        notes=(str, ""),
    )


def final_result_instructions(output_model: type[BaseModel]) -> str:
    schema = json.dumps(payload_model(output_model).model_json_schema(), sort_keys=True)
    return (
        "## Final result\n\nThe final result must be one JSON object that matches this JSON "
        f'Schema:\n{schema}\nUse "status": "ok" when you completed the task and '
        '"failed" when you could not, and say why in "notes".'
    )


def format_errors(failure: ValidationError) -> tuple[str, ...]:
    return tuple(
        f"{'.'.join(str(p) for p in error['loc']) or '(root)'}: {error['msg']}"
        for error in failure.errors()
    )


def validate_final(value: Any, output_model: type[BaseModel]) -> Validation:
    if value is None:
        return Validation(False, None, ("(root): no final result",))
    try:
        return Validation(True, payload_model(output_model).model_validate(value), ())
    except ValidationError as failure:
        return Validation(False, None, format_errors(failure))


def repair_message(errors: tuple[str, ...], json_protocol: bool) -> str:
    listed = "\n".join(f"- {e}" for e in errors)
    shape = "as a final action" if json_protocol else "as one JSON object, without a tool call"
    return (
        "VALIDATION ERROR: your final result does not match the required schema:\n"
        f"{listed}\nReply again with the corrected final result {shape}."
    )


def build_result(
    task: TaskV1,
    *,
    status: str,
    output_ref: str,
    input_tokens: int,
    output_tokens: int,
    usd: float,
    schema_valid: bool,
    notes: str,
) -> ResultV1:
    """result_v1 from the harness's own facts, validated against the contract."""
    return ResultV1.model_validate(
        {
            "task_id": task.task_id,
            "status": status,
            "output_ref": output_ref,
            "usage": ResultUsage(
                input_tokens=input_tokens, output_tokens=output_tokens, usd=usd
            ).model_dump(),
            "self_check": SelfCheck(schema_valid=schema_valid, notes=notes).model_dump(),
        }
    )
