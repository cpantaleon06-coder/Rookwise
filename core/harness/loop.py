"""The tool loop: model proposes a tool call, the harness runs it, the result goes back.

Every model call goes through `Harness.complete`, so the ledger, rate limits, retries
and cassettes apply unchanged. Two protocols, chosen per model in config/harness.json
(`loop_protocol`) or per call:

- `json_protocol` (the baseline, works on every model): the model replies with one JSON
  object, `{"action": "tool", "name": ..., "args": {...}}` or
  `{"action": "final", "result": ...}`, sent with `response_format: json_object`. Tool
  results come back in a user message starting with "TOOL RESULT".
- `native_tools`: OpenAI-style `tools`; results come back as `tool` messages. The final
  answer is a reply without tool calls whose content is one JSON object.

Limits (config `loop`): `max_steps` model steps per run; `max_protocol_errors` replies
that break the protocol (fed back to the model each time); `max_repeats` repeats of
one identical tool call; `tool_timeout_s` per tool; tool results longer than
`tool_result_max_tokens` are truncated before they go back to the model.

Tool failures (unknown tool, bad arguments, unavailable, timeout, exception) never raise
through the loop: they go back to the model as `{"ok": false, "error": {...}}`.

`finish_reason: "length"` is never a success (D3): the reply is discarded and the run
ends at once with status `length`, and `LoopOutcome.length` says which ceiling cut it:
the call's own `max_tokens` (the role's output ceiling, config/skills.json) or what was
left of the task's output token budget. It is never retried: a retry with the same
ceiling would pay again for the same cut.

A `TokenBudget` (from task_v1) is enforced from the ledger's own entries for the task:
a step that could pass it is not sent. USD caps are the ledger's, through reservations.

In record mode every tool execution is written to the cassette, keyed by tool name and
arguments; replay returns the recorded result and never runs the tool.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from rookwise.harness.cassette import canonical_json, request_key
from rookwise.harness.client import CancelHandle, Harness, Result
from rookwise.harness.config import LoopConfig, LoopProtocol
from rookwise.harness.events import ToolCall
from rookwise.harness.request import ChatRequest, JsonObjectFormat, build_request
from rookwise.harness.retry import ApiError, StreamInterrupted
from rookwise.ledger import CapReached
from rookwise.money import ZERO_USD

LoopStatus = Literal[
    "final",
    "step_limit",
    "protocol_error",
    "repeated_tool_call",
    "length",
    "token_ceiling",
    "budget_exhausted",
    "cancelled",
    "interrupted",
    "api_error",
]
PROTOCOL_HEADING = "## Tool protocol"
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


@dataclass(frozen=True)
class ToolContext:
    run_id: str
    task_id: str


ToolHandler = Callable[[dict[str, Any], ToolContext], Awaitable[Any]]


@dataclass(frozen=True)
class Tool:
    """A tool the model may call. `parameters` is the JSON Schema of its arguments.

    `unavailable` returns a reason when the tool cannot run (for example a missing key);
    such a tool is not offered to the model, and calling it anyway returns an error.
    """

    name: str
    description: str
    parameters: Mapping[str, Any]
    handler: ToolHandler
    timeout_s: float | None = None
    unavailable: Callable[[], str | None] | None = None

    def unavailable_reason(self) -> str | None:
        return self.unavailable() if self.unavailable is not None else None

    def native_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.parameters),
            },
        }


@dataclass(frozen=True)
class TokenBudget:
    """Token ceilings for one operator call, summed over every model call for the task."""

    max_input_tokens: int
    max_output_tokens: int


@dataclass(frozen=True)
class LengthStop:
    """A reply cut by `finish_reason: "length"`. `limited_by` is `output_ceiling` when the
    call had its full `max_tokens`, `token_budget` when the task's remaining output token
    budget had lowered it."""

    max_tokens: int
    limited_by: Literal["output_ceiling", "token_budget"]


@dataclass
class LoopOutcome:
    status: LoopStatus
    model: str
    protocol: LoopProtocol
    final: Any = None
    final_text: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    steps: int = 0
    model_calls: int = 0
    length: LengthStop | None = None
    usd: Decimal = ZERO_USD
    usage_estimated: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: Counter[str] = field(default_factory=Counter)
    trace: list[dict[str, Any]] = field(default_factory=list)
    detail: str = ""


class _ToolAction(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action: Literal["tool"]
    name: str
    args: dict[str, Any] = {}


class _FinalAction(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action: Literal["final"]
    result: Any


@dataclass(frozen=True)
class _Reply:
    text: str
    tool_calls: tuple[ToolCall, ...]


@dataclass(frozen=True)
class _Stop:
    status: LoopStatus
    detail: str = ""


def parse_json_text(text: str) -> tuple[Any, str | None]:
    """The JSON value in a reply (a ```json fence is tolerated), or an error message."""
    fenced = _FENCE.match(text)
    candidate = fenced.group(1) if fenced else text.strip()
    if not candidate:
        return None, "the reply is empty"
    try:
        return json.loads(candidate), None
    except json.JSONDecodeError as error:
        return None, f"the reply is not valid JSON ({error.msg} at character {error.pos})"


def parse_action(text: str) -> tuple[_ToolAction | _FinalAction | None, str | None]:
    value, error = parse_json_text(text)
    if error is not None:
        return None, error
    if not isinstance(value, dict):
        return None, "the reply must be a JSON object"
    kind = value.get("action")
    model = {"tool": _ToolAction, "final": _FinalAction}.get(kind)  # type: ignore[arg-type]
    if model is None:
        return None, 'the "action" field must be "tool" or "final"'
    try:
        return model.model_validate(value), None
    except ValidationError as failure:
        problems = "; ".join(
            f"{'.'.join(map(str, e['loc'])) or 'reply'}: {e['msg']}" for e in failure.errors()
        )
        return None, f"invalid {kind} action: {problems}"


def protocol_block(protocol: LoopProtocol, tools: Sequence[Tool]) -> str:
    if protocol == "native_tools":
        return (
            f"{PROTOCOL_HEADING}\n\nCall a tool when you need one. Each tool result comes "
            'back as a tool message holding {"ok": true, "result": ...} or {"ok": false, '
            '"error": {"type": ..., "message": ...}}. When you are done, reply without a '
            "tool call, with only the final result as one JSON object and nothing else."
        )
    lines = [
        PROTOCOL_HEADING,
        "",
        "Reply with exactly one JSON object and nothing else.",
        '- To call a tool: {"action": "tool", "name": "<tool name>", "args": {...}}',
        '- To finish: {"action": "final", "result": <the final result>}',
        'Tool results come back in a user message that starts with "TOOL RESULT". It holds '
        '{"ok": true, "result": ...} or {"ok": false, "error": {"type": ..., "message": ...}}.',
        "",
    ]
    if not tools:
        lines.append("No tools are available: reply with a final action.")
    else:
        lines.append("Tools:")
        for tool in tools:
            schema = json.dumps(tool.parameters, sort_keys=True)
            lines.append(f"- {tool.name}: {tool.description} Arguments (JSON Schema): {schema}")
    return "\n".join(lines)


def prepare_messages(
    messages: Sequence[Mapping[str, Any]], protocol: LoopProtocol, tools: Sequence[Tool]
) -> list[dict[str, Any]]:
    """Add the protocol block to the first system message (or a new one in front)."""
    block = protocol_block(protocol, tools)
    prepared = [dict(m) for m in messages]
    if prepared and prepared[0].get("role") == "system":
        prepared[0]["content"] = f"{prepared[0].get('content', '')}\n\n{block}".strip()
    else:
        prepared.insert(0, {"role": "system", "content": block})
    return prepared


def _error(kind: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"type": kind, "message": message}}


class ToolLoop:
    """Runs one model through the tool loop. Holds no state between runs."""

    def __init__(
        self, harness: Harness, tools: Sequence[Tool] = (), config: LoopConfig | None = None
    ) -> None:
        self._harness = harness
        self._tools = {tool.name: tool for tool in tools}
        self._limits = config or harness.config.loop

    def offered_tools(self) -> list[Tool]:
        """Tools offered to the model. Replay offers every tool, since it runs none, so the
        recorded requests match whatever keys are present."""
        if self._harness.mode == "replay":
            return list(self._tools.values())
        return [t for t in self._tools.values() if t.unavailable_reason() is None]

    async def run(
        self,
        request: ChatRequest,
        *,
        protocol: LoopProtocol | None = None,
        history: Sequence[Mapping[str, Any]] | None = None,
        budget: TokenBudget | None = None,
        cancel: CancelHandle | None = None,
    ) -> LoopOutcome:
        """Run until a final answer or a stop. `history` continues an earlier run (its
        messages already hold the protocol block); otherwise `request.messages` is used."""
        config = self._harness.config
        protocol = protocol or config.model(request.model).loop_protocol
        tools = self.offered_tools()
        cancel = cancel or CancelHandle()
        messages = (
            [dict(m) for m in history]
            if history is not None
            else prepare_messages(request.messages, protocol, tools)
        )
        outcome = LoopOutcome(status="step_limit", model=request.model, protocol=protocol)
        seen: Counter[str] = Counter()
        protocol_errors = 0
        context = ToolContext(request.run_id, request.task_id)
        try:
            while outcome.steps < self._limits.max_steps:
                if cancel.cancelled:
                    outcome.status = "cancelled"
                    break
                outcome.steps += 1
                reply = await self._model_step(
                    request, messages, protocol, tools, budget, cancel, outcome
                )
                if isinstance(reply, _Stop):
                    outcome.status, outcome.detail = reply.status, reply.detail
                    break
                calls, problem, final = self._read_reply(reply, protocol, messages)
                if final is not None:
                    outcome.status, outcome.final, outcome.final_text = (
                        "final",
                        final[0],
                        reply.text,
                    )
                    outcome.trace.append({"step": outcome.steps, "kind": "final"})
                    break
                if problem is not None:
                    protocol_errors += 1
                    outcome.trace.append(
                        {"step": outcome.steps, "kind": "protocol_error", "detail": problem}
                    )
                    if protocol_errors > self._limits.max_protocol_errors:
                        outcome.status, outcome.detail = "protocol_error", problem
                        break
                    messages.append(
                        {"role": "user", "content": self._protocol_error(problem, protocol)}
                    )
                    continue
                stop = await self._run_calls(
                    calls, protocol, messages, seen, context, cancel, outcome
                )
                if stop is not None:
                    outcome.status, outcome.detail = stop.status, stop.detail
                    break
        finally:
            outcome.messages = messages
        return outcome

    # -- model step ----------------------------------------------------------------------

    async def _model_step(
        self,
        request: ChatRequest,
        messages: list[dict[str, Any]],
        protocol: LoopProtocol,
        tools: Sequence[Tool],
        budget: TokenBudget | None,
        cancel: CancelHandle,
        outcome: LoopOutcome,
    ) -> _Reply | _Stop:
        config = self._harness.config
        max_tokens = request.max_tokens or config.model(request.model).max_tokens
        if protocol == "native_tools":
            shape = {
                "tools": tuple(t.native_spec() for t in tools),
                "tool_choice": "auto" if tools else None,
                "response_format": None,
            }
        else:
            json_object = self._limits.json_protocol_response_format == "json_object"
            shape = {
                "tools": (),
                "tool_choice": None,
                "response_format": JsonObjectFormat() if json_object else None,
            }
        step_max = max_tokens
        if budget is not None:
            used_in, used_out = self._used_tokens(request)
            remaining = budget.max_output_tokens - used_out
            if remaining <= 0:
                return _Stop("token_ceiling", "output token budget used up")
            step_max = min(max_tokens, remaining)
        step = dataclasses.replace(
            request, messages=tuple(dict(m) for m in messages), max_tokens=step_max, **shape
        )
        if budget is not None:
            estimate = build_request(step, config).input_tokens_estimate
            if used_in + estimate > budget.max_input_tokens:
                return _Stop("token_ceiling", "input token budget would be passed")
        try:
            result = await self._harness.complete(step, cancel)
        except CapReached as stop:
            return _Stop("budget_exhausted", str(stop))
        except StreamInterrupted as error:
            outcome.model_calls += 1
            outcome.usd += error.usd
            outcome.usage_estimated |= error.usage_estimated
            return _Stop("interrupted", error.message)
        except ApiError as error:
            return _Stop("api_error", str(error))
        self._count(result, outcome)
        if result.cancelled:
            return _Stop("cancelled")
        if result.finish_reason == "length":
            # D3: never a success; the content is discarded and nothing is retried.
            limited_by = "output_ceiling" if step_max == max_tokens else "token_budget"
            outcome.length = LengthStop(step_max, limited_by)
            outcome.trace.append(
                {
                    "step": outcome.steps,
                    "kind": "length",
                    "max_tokens": step_max,
                    "limited_by": limited_by,
                }
            )
            return _Stop("length", f"finish_reason length at max_tokens {step_max} ({limited_by})")
        return _Reply(result.text, result.tool_calls)

    @staticmethod
    def _count(result: Result, outcome: LoopOutcome) -> None:
        outcome.model_calls += 1
        outcome.usd += result.usd
        outcome.usage_estimated |= result.usage_estimated
        outcome.input_tokens += result.usage.input_tokens
        outcome.output_tokens += result.usage.output_tokens

    def _used_tokens(self, request: ChatRequest) -> tuple[int, int]:
        entries = [
            e
            for e in self._harness.ledger.report(request.run_id).entries
            if e.task_id == request.task_id
        ]
        return sum(e.input_tokens for e in entries), sum(e.output_tokens for e in entries)

    # -- reading replies -----------------------------------------------------------------

    def _read_reply(
        self, reply: _Reply, protocol: LoopProtocol, messages: list[dict[str, Any]]
    ) -> tuple[list[tuple[str, Any, str | None]], str | None, tuple[Any] | None]:
        """(tool calls, protocol problem, (final value,)) and the assistant message."""
        if protocol == "json_protocol":
            messages.append({"role": "assistant", "content": reply.text})
            action, problem = parse_action(reply.text)
            if action is None:
                return [], problem, None
            if isinstance(action, _FinalAction):
                return [], None, (action.result,)
            return [(action.name, action.args, None)], None, None
        if reply.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": reply.text or None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {"name": call.name, "arguments": call.arguments},
                        }
                        for call in reply.tool_calls
                    ],
                }
            )
            calls = []
            for call in reply.tool_calls:
                args, problem = parse_json_text(call.arguments or "{}")
                calls.append((call.name, args if problem is None else _BadArgs(problem), call.id))
            return calls, None, None
        messages.append({"role": "assistant", "content": reply.text})
        value, problem = parse_json_text(reply.text)
        if problem is not None:
            return [], problem, None
        return [], None, (value,)

    @staticmethod
    def _protocol_error(problem: str, protocol: LoopProtocol) -> str:
        if protocol == "json_protocol":
            expected = "exactly one JSON object: a tool action or a final action"
        else:
            expected = "a tool call, or only the final result as one JSON object"
        return f"PROTOCOL ERROR: {problem}. Reply with {expected}."

    # -- tools ---------------------------------------------------------------------------

    async def _run_calls(
        self,
        calls: list[tuple[str, Any, str | None]],
        protocol: LoopProtocol,
        messages: list[dict[str, Any]],
        seen: Counter[str],
        context: ToolContext,
        cancel: CancelHandle,
        outcome: LoopOutcome,
    ) -> _Stop | None:
        for name, args, call_id in calls:
            if not isinstance(args, _BadArgs):
                key = f"{name}:{canonical_json({'args': args})}"
                seen[key] += 1
                if seen[key] > self._limits.max_repeats + 1:
                    return _Stop("repeated_tool_call", f"{name} called again with the same args")
            envelope = await self._tool_result(name, args, context, cancel, outcome)
            if envelope is None:
                return _Stop("cancelled", f"cancelled while {name} ran")
            outcome.trace.append(
                {
                    "step": outcome.steps,
                    "kind": "tool",
                    "tool": name,
                    "ok": envelope.get("ok") is True,
                }
            )
            text = self._render(envelope)
            if protocol == "native_tools":
                messages.append(
                    {"role": "tool", "tool_call_id": call_id, "name": name, "content": text}
                )
            else:
                messages.append({"role": "user", "content": f"TOOL RESULT for {name}:\n{text}"})
        return None

    async def _tool_result(
        self,
        name: str,
        args: Any,
        context: ToolContext,
        cancel: CancelHandle,
        outcome: LoopOutcome,
    ) -> dict[str, Any] | None:
        """The result envelope, or None when the call was cancelled."""
        tool = self._tools.get(name)
        if tool is None:
            known = ", ".join(sorted(t.name for t in self.offered_tools())) or "none"
            return _error("unknown_tool", f"no tool named {name!r}; available: {known}")
        if isinstance(args, _BadArgs):
            return _error("bad_args", f"arguments are not valid JSON: {args.problem}")
        if not isinstance(args, dict):
            return _error("bad_args", "arguments must be a JSON object")
        missing = [k for k in tool.parameters.get("required", []) if k not in args]
        if missing:
            return _error("bad_args", f"missing required arguments: {', '.join(missing)}")
        harness = self._harness
        reason = None if harness.mode == "replay" else tool.unavailable_reason()
        if reason is not None:
            return _error("unavailable", reason)
        cassette = harness.cassette
        key = index = None
        if cassette is not None:
            key = request_key({"tool": name, "args": args})
            index = cassette.next_index(key)
        outcome.tool_calls[name] += 1
        if harness.mode == "replay":
            assert cassette is not None and key is not None and index is not None
            return cassette.lookup(key, index)["envelope"]
        envelope = await self._execute(tool, args, context, cancel)
        if envelope is not None and harness.mode == "record":
            assert cassette is not None
            cassette.put(
                {
                    "kind": "tool",
                    "key": key,
                    "index": index,
                    "request": {"tool": name, "args": args},
                    "envelope": envelope,
                }
            )
        return envelope

    async def _execute(
        self, tool: Tool, args: dict[str, Any], context: ToolContext, cancel: CancelHandle
    ) -> dict[str, Any] | None:
        timeout = tool.timeout_s if tool.timeout_s is not None else self._limits.tool_timeout_s
        task = asyncio.create_task(asyncio.wait_for(tool.handler(dict(args), context), timeout))
        unsubscribe = cancel._subscribe(task.cancel)
        try:
            return {"ok": True, "result": await task}
        except TimeoutError:
            return _error("timeout", f"{tool.name} gave no result within {timeout} s")
        except asyncio.CancelledError:
            if cancel.cancelled and not task_cancelling():
                return None
            raise
        except Exception as failure:  # a tool error goes back to the model, never up
            return _error("tool_error", f"{type(failure).__name__}: {failure}"[:500])
        finally:
            unsubscribe()

    def _render(self, envelope: dict[str, Any]) -> str:
        text = json.dumps(envelope, ensure_ascii=False, default=str)
        cap = int(self._limits.tool_result_max_tokens * self._harness.config.chars_per_token)
        if len(text) <= cap:
            return text
        return json.dumps(
            {
                "ok": envelope.get("ok"),
                "truncated": True,
                "original_characters": len(text),
                "content": text[:cap],
            },
            ensure_ascii=False,
        )


@dataclass(frozen=True)
class _BadArgs:
    problem: str


def task_cancelling() -> bool:
    """True when the current task itself is being cancelled (asyncio cancellation)."""
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0
