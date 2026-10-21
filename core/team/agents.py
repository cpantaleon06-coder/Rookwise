"""Model calls of the director, managers and auditor, and the events of every call.

`AgentCaller.call` composes the role's system prompt (base prompt, then the role's skills,
`rookwise.skills`), adds the final-result instructions for the output model, and runs one
`run_with_escalation` with no tools, so validation, repairs, the escalation ladder and the
ledger apply exactly as for operators. `emit_attempts` turns attempt records and their
ledger entries into contract events: per attempt `task_started`, `attempt_recorded`, then
a `budget_update` for each entry the attempt charged. Events for one call are emitted
when the call returns.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from rookwise.api.models import (
    AgentNode,
    AttemptRecordedPayload,
    BudgetUpdatePayload,
    TaskStartedPayload,
)
from rookwise.harness import AttemptRecord, EscalationResult, Harness, ToolLoop, run_with_escalation
from rookwise.harness.request import ChatRequest, JsonSchemaFormat
from rookwise.harness.validate import final_result_instructions
from rookwise.money import ZERO_USD
from rookwise.schemas import LedgerEntry, Level
from rookwise.skills import compose_system_prompt
from rookwise.team.config import RoleSpec
from rookwise.team.events import EventLog


class AgentCaller:
    def __init__(
        self,
        harness: Harness,
        log: EventLog,
        *,
        skills_config: dict[str, Any] | None,
        skills_dir: Path,
    ) -> None:
        self.harness = harness
        self.log = log
        self.skills_config = skills_config
        self.skills_dir = skills_dir

    async def call(
        self,
        agent: AgentNode,
        role: RoleSpec,
        *,
        level: Level,
        task_id: str,
        base_prompt: str,
        user: str,
        output_model: type[BaseModel],
        budget_id: str | None,
        response_format: JsonSchemaFormat | None = None,
    ) -> EscalationResult:
        composed = compose_system_prompt(
            role.role, base_prompt, config=self.skills_config, skills_dir=self.skills_dir
        )
        system = f"{composed.text}\n\n{final_result_instructions(output_model)}"
        request = ChatRequest(
            model=role.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            run_id=self.log.run_id,
            level=level,
            task_id=task_id,
            max_tokens=role.max_output_tokens,
            skills=composed.skill_ids,
            budget_id=budget_id,
            response_format=response_format,
        )
        result = await run_with_escalation(
            ToolLoop(self.harness, ()),
            request,
            output_model,
            config=self.harness.config.escalation,
            repair_temperature=role.repair_temperature,
        )
        self.emit_attempts(agent.agent_id, result.attempts, self.entries(task_id))
        return result

    def entries(self, task_id: str) -> list[LedgerEntry]:
        report = self.harness.ledger.report(self.log.run_id)
        return [e for e in report.entries if e.task_id == task_id]

    def emit_attempts(
        self, agent_id: str, attempts: Sequence[AttemptRecord], entries: Sequence[LedgerEntry]
    ) -> None:
        pending = list(entries)
        for attempt in attempts:
            self.log.emit(
                "task_started",
                TaskStartedPayload(
                    task_id=attempt.task_id,
                    agent_id=agent_id,
                    model=attempt.model,
                    attempt_index=attempt.attempt_index,
                ),
            )
            self.log.emit(
                "attempt_recorded", AttemptRecordedPayload(agent_id=agent_id, attempt=attempt)
            )
            charged, pending = pending[: attempt.model_calls], pending[attempt.model_calls :]
            for entry in charged:
                self.budget_update(entry)
        for entry in pending:
            self.budget_update(entry)

    def budget_update(self, entry: LedgerEntry) -> None:
        """Totals as of `entry`: absolute, so a repeated event is harmless."""
        report = self.harness.ledger.report(self.log.run_id)
        position = next(i for i, e in enumerate(report.entries) if e is entry)
        upto = report.entries[: position + 1]
        by_level: dict[str, Any] = {}
        for e in upto:
            by_level[e.level] = by_level.get(e.level, ZERO_USD) + e.usd_real
        self.log.emit(
            "budget_update",
            BudgetUpdatePayload(
                spent_usd=sum((e.usd_real for e in upto), ZERO_USD),
                held_usd=report.held_usd,
                predicted_usd=sum((e.usd_predicted for e in upto), ZERO_USD),
                cap_usd=report.caps.run_usd,
                spent_by_level=by_level,
                entry=entry,
            ),
        )
