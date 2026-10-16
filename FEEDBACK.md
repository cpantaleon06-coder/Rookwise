# Feedback log (Nebius Token Factory and NVIDIA Nemotron)

Only add entries confirmed with a real call or a quoted doc page.

Kept from day one for the hackathon feedback requirement. One entry per finding: date, what happened, what would help.

## 2026-10-12
- Docs: the function calling page lists no supported models and does not mention Nemotron. Could not tell from the docs whether Nemotron models support `tools`. Source: https://docs.tokenfactory.nebius.com/ai-models-inference/function-calling.md
- Docs: the quickstart does not cover rate limits, tool calling, or JSON mode; they live on separate pages that are easy to miss. Source: https://docs.tokenfactory.nebius.com/quickstart.md
- Docs: the rate limits page gives an example baseline (60 RPM, 400,000 TPM) and says real defaults are in the console. A per-model table in the docs would help. Source: https://docs.tokenfactory.nebius.com/ai-models-inference/rate-limits.md

## 2026-10-13
- API: `nvidia/Nemotron-3_5-Lightning` puts its reasoning in `content` when output is cut off by `max_tokens`. Source: real calls.
  - Sent: chat completions with `max_tokens=600` and reasoning on (default, `reasoning_effort: "high"`, or `chat_template_kwargs.enable_thinking: true`).
  - Observed: 6 calls ended with `finish_reason: "length"`. In 5, `content` held untagged thinking ("Here's a thinking process: ...") with no answer, the `reasoning` fields were empty and `reasoning_tokens` was 600. In the Spanish prompt the reasoning came in `reasoning` and `reasoning_content`, and the answer in `content` was cut mid-sentence.
  - Reproduce: `python scripts/smoke_test.py --models nvidia/Nemotron-3_5-Lightning` (tests plain_chat, reason_default, effort_high, thinking_on, non_english).
  - What would help: keep reasoning out of `content` even when generation stops at `max_tokens`, or document this behavior.
- API: `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` with `reasoning_effort: "none"` returns `content: null` and puts the answer in the `reasoning` field. Source: real call.
  - Sent: one chat completion with `reasoning_effort: "none"`, `max_tokens=600` and the prompt "A shop sells 3 pens for $2. How much do 12 pens cost? Reply with only the amount."
  - Observed: HTTP 200, `finish_reason: "stop"`, 2 completion tokens, `content: null`, `reasoning: "8"`. The same prompt with `chat_template_kwargs.enable_thinking: false` returned "$8" in `content`. One sample.
  - Reproduce: `python scripts/smoke_test.py --models nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` (tests effort_none and thinking_off).
  - What would help: return the answer in `content` when reasoning is off, or document which reasoning control Nano supports.
- API: Nano does not return `usage.completion_tokens_details.reasoning_tokens`; Ultra, Super and Lightning do. Source: real calls.
  - Sent: the same 12 smoke test calls to each of the four Nemotron models.
  - Observed: `completion_tokens_details` was null (absent) on all 11 successful Nano calls, although 10 of them carried reasoning text in the `reasoning` field. So reasoning tokens cannot be told apart from answer tokens on Nano.
  - Reproduce: `python scripts/smoke_test.py`, then compare `usage` per model in `runs/smoke_test.json`.
  - What would help: report `reasoning_tokens` for every model that reasons.
- Docs/API mismatch: the structured output page sets `json_schema` to a bare schema in its request examples, but the API requires the `{name, schema}` wrapper. Source: https://docs.tokenfactory.nebius.com/ai-models-inference/json.md and real calls.
  - Sent: `response_format: {"type": "json_schema", "json_schema": <schema>}`, the shape of the page's Python example (`"json_schema": Film.model_json_schema()`) and cURL example (`"json_schema": '"$SCHEMA"'`, with a bare schema in `SCHEMA`).
  - Observed: HTTP 422 on all four Nemotron models, `"msg": "Field required"` for `["body", "response_format", "json_schema", "name"]` and for `[..., "json_schema", "schema"]` (full detail in `docs/HARNESS_RESEARCH.md`). The wrapped form, as in the page's "Example of a valid JSON schema", worked on all four.
  - Reproduce: `python scripts/smoke_test.py` (tests json_bare and json_wrapped).
  - What would help: use the wrapped `{name, schema, strict}` form in every request example on the page.

## 2026-10-15
- Docs/API: on Nemotron, the reasoning switch that worked on every model is `chat_template_kwargs.enable_thinking`, which the chat completion reference does not list. Source: https://docs.tokenfactory.nebius.com/api-reference/inference/create-chat-completion.md and real calls.
  - Sent: `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` through the OpenAI SDK (a top-level body field), with the wrapped json_schema form.
  - Observed: the reference documents `reasoning_effort` (none, minimal, low, medium, high, xhigh, max) and no `chat_template_kwargs`. With `enable_thinking` false, Lightning and Ultra returned schema-valid JSON in 60 of 60 calls, with `reasoning_tokens` 0 and no length cutoffs. In the 2026-10-13 smoke test it gave correct short answers on all four models, while `reasoning_effort: "none"` on Nano returned `content: null`.
  - Reproduce: `python scripts/skill_check.py`, and `python scripts/smoke_test.py` for the four-model comparison.
  - What would help: document `chat_template_kwargs.enable_thinking` for Nemotron models, and say which reasoning control each model honors.

## 2026-10-16
- API: `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` tool calling was unreliable in streaming calls with one function tool (`add(a, b)`). Source: real calls, one sample each.
  - Sent: streaming chat completions with `tools`, reasoning off unless stated, prompt "Use the add tool to compute 17 + 25. Do not compute it yourself."
  - Observed, `tool_choice` naming the function: the response carried a tool call, but `finish_reason` was `"stop"`, not `"tool_calls"`.
  - Observed, `tool_choice: "auto"` with reasoning on (`chat_template_kwargs.enable_thinking: true`): `finish_reason: "tool_calls"`, but the streamed argument pieces were `{`, `"a": 17` and `{}`, which do not join into valid JSON.
  - Observed, follow-up turn (the tool call plus a `tool` message with the result `42`): the model called `add` again, with text content, instead of answering.
  - Observed: a late tool-call fragment repeated the `id` and `type` keys with `id: null`.
  - For comparison: Ultra, Super and Lightning returned well-formed tool calls in the same cases and answered after the tool result.
  - Reproduce: `python scripts/tool_probe.py` (calls `forced`, `reasoning_on`, `follow_up`); details in `docs/HARNESS_RESEARCH.md`, "Tool-calling probe".
- API: sending `tools` together with a json_schema `response_format` made all four Nemotron models skip the tool. Source: real calls, one sample each.
  - Sent: `tools` with `add(a, b)`, `tool_choice: "auto"`, and `response_format: {"type": "json_schema", "json_schema": {"name": "sum_answer", "schema": {"sum": integer}, "strict": true}}`, prompt asking to use the tool and then answer as JSON.
  - Observed: HTTP 200 on Ultra, Super, Lightning and Nano, no tool call, `finish_reason: "stop"`, content `{"sum": 42}` (Nano: `{ "sum": 42 }`).
  - Reproduce: `python scripts/tool_probe.py` (call `with_schema`).
