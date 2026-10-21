# core/harness

The harness is the only code in Rookwise that calls the model API (Nebius Token Factory). The public surface is documented at the top of `__init__.py`; settings and model quirks live in `config/harness.json`. Facts about the API come from `docs/HARNESS_RESEARCH.md` and are marked VERIFIED or UNVERIFIED there.

| Module | Job |
|---|---|
| `client.py` | Streaming calls, ledger reserve, charge and release, retries, cancellation, record and replay |
| `loop.py` | The tool loop (this page) |
| `validate.py` | Final answer validation and the result_v1 built from it |
| `escalate.py` | Repairs, the escalation ladder and the per-attempt records |
| `request.py`, `sse.py`, `events.py`, `cost.py`, `ratelimit.py`, `retry.py`, `cassette.py`, `config.py` | Building blocks |

## Tool loop protocols

`ToolLoop(harness, tools).run(request)` runs one model until it gives a final answer or a limit stops it. Every model call goes through `Harness.complete`, so the ledger, rate limits, retries and cassettes apply to each step. The protocol is chosen per model with `loop_protocol` in `config/harness.json`, or per call.

### json_protocol (baseline)

Works on every model and is the one the loop always supports. The model gets a protocol block in its system message and replies with exactly one JSON object, sent with `response_format: {"type": "json_object"}`:

```json
{"action": "tool", "name": "search", "args": {"query": "Nemotron"}}
{"action": "final", "result": {"status": "ok", "output": {"answer": "..."}, "notes": ""}}
```

Tool results come back as a user message that starts with `TOOL RESULT for <name>:` and holds `{"ok": true, "result": ...}` or `{"ok": false, "error": {"type": ..., "message": ...}}`. A reply that is not a valid action gets a `PROTOCOL ERROR` message and counts against `max_protocol_errors`. For a reply that is not valid JSON (in either protocol) the message holds the parser's error, its line and column (or "the end of the reply"), about 80 characters around it with the position marked `<<ERROR HERE>>`, and the `{` and `[` still open at the end, and asks for the complete corrected JSON only. Nothing is repaired by the harness. A reply byte-identical to the previous invalid reply is not answered with the same message again: the loop stops with status `repeated_invalid_reply`, and the escalation ladder moves to the next model if there is one.

### native_tools

OpenAI-style `tools` with `tool_choice: "auto"`. The streamed tool-call fragments are joined per index (`events.assemble_tool_calls`); results go back as `tool` messages with the matching `tool_call_id`. The final answer is a reply without tool calls whose content is one JSON object. `response_format` is never sent together with `tools`: in the tool-calling probe every model skipped the tools when both were present.

### Which model uses which

From the tool-calling probe of 2026-10-16 (one sample per call, so weak evidence):

| Model | Protocol | Why |
|---|---|---|
| Ultra, Super, Lightning | `native_tools` | Tool calls in auto, forced and reasoning-on modes, parseable arguments, a final answer after the tool result |
| Nano | `json_protocol` | Malformed arguments with reasoning on, `finish_reason: "stop"` on a forced call, and a repeated tool call instead of a final answer |

### Limits and failures

- `max_steps` model steps per run; `max_repeats` repeats of one identical call (same name and arguments) before the run stops; `tool_timeout_s` per tool.
- Tool results longer than `tool_result_max_tokens` (converted with `input_estimate.chars_per_token`) are truncated before they go back, as `{"ok": ..., "truncated": true, "original_characters": n, "content": "..."}`.
- Unknown tools, bad arguments, missing keys (`unavailable`), timeouts and exceptions go back to the model as structured errors; they never raise through the loop.
- `finish_reason: "length"` is never a success: the reply is discarded and the run ends at once as `length`, with `LoopOutcome.length` naming the ceiling that cut it (the call's `max_tokens`, or what was left of the task's output token budget). It is not retried and does not escalate. Team and operator calls are sent with their role's `max_output_tokens` (config/skills.json), which is what the ledger reserves.
- A `TokenBudget` (from task_v1) is checked against the ledger's entries for the task before each step; the task's USD cap is the ledger's own.
- Cancellation (asyncio or a `CancelHandle`) stops the run and the client settles every reservation.

### Record and replay

In record mode each tool execution is written to the cassette next to the model calls, keyed by the tool name and arguments with a sequence index. Replay returns the recorded results and never runs a tool or calls the API, so a full tool run replays offline with identical ledger charges (`tests/fixtures/cassettes/operator_tool_run.json`).

## After the loop

`run_with_escalation` validates the final result against the operator's output model (`{"status", "output", "notes"}`), feeds validation errors back for up to `escalation.max_repairs` repairs, then moves up `escalation.next` (Lightning or Nano to Super, Super to Ultra) while the ledger allows it. Each attempt yields an `AttemptRecord` (model, index, reason, validation errors, cost, `usage_estimated`), and the call gets one label: `first_pass_ok`, `ok_after_retry`, `ok_after_escalation` or `failed`. `rookwise.runner.run_operator` wraps all of this for one task_v1 and returns result_v1.
