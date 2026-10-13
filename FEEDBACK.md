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
