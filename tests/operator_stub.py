"""A stub operator for runner tests. It uses a test-only skill (tests/fixtures/skills) and
an output model of its own, so it depends on no demo domain."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from rookwise.runner import OperatorSpec
from rookwise.schemas import TaskV1
from rookwise.store import InMemoryStore

SKILLS_DIR = Path(__file__).resolve().parent / "fixtures" / "skills"
SKILLS_CONFIG: dict[str, Any] = {
    "skills": {"stub-notes": {"max_tokens": 100}},
    "roles": {
        "stub-operator": {
            "model": "nemotron-3.5-lightning",
            "max_output_tokens": 2048,
            "skills": ["stub-notes"],
            "max_skill_tokens": 100,
        }
    },
}
INSTRUCTION_REF = "store://r-1/briefs/t-1"
INPUT_REF = "store://r-1/results/t-0"


class StubFindings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    sources: list[str]


def stub_spec(**overrides: Any) -> OperatorSpec:
    data: dict[str, Any] = {
        "operator_id": "stub-operator-lightning-01",
        "role": "stub-operator",
        "model": "nemotron-3.5-lightning",
        "price_per_task_est_usd": Decimal("0.002"),
        "avg_latency_s": 8,
        "reputation": 0.5,
        "tools": ["tavily_search"],
        "skills": ["stub-notes"],
        "input_schema": "task_v1",
        "output_schema": "result_v1",
    }
    return OperatorSpec.model_validate(data | overrides)


def stub_task(max_usd: Decimal = Decimal("0.05"), **budget: int) -> TaskV1:
    return TaskV1.model_validate(
        {
            "task_id": "t-1",
            "run_id": "r-1",
            "role": "stub-operator",
            "instruction_ref": INSTRUCTION_REF,
            "inputs": [INPUT_REF],
            "budget": {
                "max_input_tokens": budget.get("max_input_tokens", 50_000),
                "max_output_tokens": budget.get("max_output_tokens", 5_000),
                "max_usd": max_usd,
            },
            "deadline_s": 60,
        }
    )


def stub_store() -> InMemoryStore:
    return InMemoryStore(
        {
            INSTRUCTION_REF: "Find out which company makes the Nemotron models.",
            INPUT_REF: {"hint": "Search the web once."},
        }
    )
