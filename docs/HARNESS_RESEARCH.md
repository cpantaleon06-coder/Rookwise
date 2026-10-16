# Harness research: Nebius Token Factory and Nemotron

Researched October 12, 2026 from the official Token Factory docs and one third-party source. Updated October 13, 2026 with the first real smoke test (`scripts/smoke_test.py`; raw results in `runs/smoke_test.json`, not committed). Each item is marked VERIFIED (read in the docs, or observed in a real call with the date), THIRD-PARTY (not from Nebius), or UNVERIFIED (not confirmed by a doc page or a real call).

Smoke test of 2026-10-13: 12 calls per model on the four Nemotron models, one sample per test, `max_tokens` 600, estimated spend USD 0.012978. One sample on short prompts shows what the API returns, not model quality.

## API basics

| Item | Status | Detail |
|---|---|---|
| Base URL | VERIFIED | `https://api.tokenfactory.nebius.com/v1/` |
| Chat endpoint | VERIFIED | `POST https://api.tokenfactory.nebius.com/v1/chat/completions` |
| Auth | VERIFIED | `Authorization: Bearer <key>` |
| OpenAI compatibility | VERIFIED | Official docs use the standard OpenAI Python and JS SDKs with a custom base URL and `NEBIUS_API_KEY` |
| Nemotron model IDs | VERIFIED (2026-10-13, observed in smoke test) | From `GET /v1/models`: `nvidia/Nemotron-3-Ultra-550b-a55b`, `nvidia/nemotron-3-super-120b-a12b`, `nvidia/Nemotron-3_5-Lightning`, `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` (case as returned). Stored in `model_ids` in `config/prices.json` |

Sources: https://docs.tokenfactory.nebius.com/quickstart.md and https://docs.tokenfactory.nebius.com/api-reference/introduction.md

## Request and response fields

Source: https://docs.tokenfactory.nebius.com/api-reference/inference/create-chat-completion.md

- VERIFIED request fields: `model`, `messages` (required); `max_tokens`, `max_completion_tokens`, `temperature`, `top_p`, `n`, `stop`, `presence_penalty`, `frequency_penalty`, `logit_bias`; `tools`, `tool_choice`; `response_format`; `reasoning_effort`; `stream`, `stream_options`; `logprobs`, `top_logprobs`; `store`, `user`, `service_tier`, `extra_body`.
- VERIFIED response: `id`, `object`, `created`, `model`, `choices`, `usage`, `service_tier`.
- VERIFIED usage fields: `prompt_tokens`, `completion_tokens`, `total_tokens`, `prompt_tokens_details.cached_tokens`, `completion_tokens_details.reasoning_tokens`.
- VERIFIED streaming: `usage` is populated only with `stream_options.include_usage`.
- VERIFIED (2026-10-13, observed in smoke test): `completion_tokens_details.reasoning_tokens` is returned by Ultra, Super and Lightning, not by Nano. Wherever it is present, `completion_tokens >= reasoning_tokens`, so reasoning tokens appear to be included in `completion_tokens`.
- UNVERIFIED: whether reasoning tokens are billed as output tokens. Until verified, the ledger treats them as output tokens (see "Cost of a call" in ARCHITECTURE.md). Compare billed usage against the console balance.
- Billing check (2026-10-13, 15:35 local time): the console credit balance showed no visible change after an estimated spend of USD 0.012978. Inconclusive; compare again after cumulative estimated spend exceeds USD 1.

### Caching

- VERIFIED (2026-10-13, observed in smoke test): the two `plain_chat` calls sent an identical 2,232-token prompt (a fixed system message plus a short user message). `prompt_tokens_details.cached_tokens` was 0 on both calls for Ultra and Super; the field was absent for Lightning and Nano. No cache discount was observed, so `cached_input` stays `null` in `config/prices.json` and the ledger falls back to the normal input price.
- UNVERIFIED: caching under other conditions (longer prompts, more repeats, other timing).

## Tool calling

Source: https://docs.tokenfactory.nebius.com/ai-models-inference/function-calling.md

- VERIFIED: OpenAI-style. Request has `tools` (type `function`, with `name`, `description`, JSON Schema `parameters`) and optional `tool_choice` (`"auto"` default, or a forced function). Response message carries `tool_calls` with `id`, `type`, and `function.name` and `function.arguments` (a JSON string). The caller executes the function and appends a message with `role: "tool"`, the matching `tool_call_id` and the function `name`.
- VERIFIED (2026-10-13, observed in smoke test): all four Nemotron models returned `tool_calls` with `finish_reason: "tool_calls"`, given one function tool (`add(a, b)`) and the default `tool_choice`.
- Calls per response. The prompt was: "Use the add tool to compute 17 + 25 and, separately, 40 + 2. Call the tool once for each sum." It asks for one call per sum but does not ask for both calls in the same response, so it did not explicitly request parallel calls. VERIFIED (2026-10-13, observed in smoke test): Lightning and Nano returned both calls in one response (2 `tool_calls`); Ultra and Super returned one call, `add(17, 25)`. The script made no follow-up turn, so a single call does not show that Ultra or Super lack parallel calls.
- UNVERIFIED: whether Ultra and Super make the second call in a following turn, and whether they return several calls in one response when asked explicitly.
- THIRD-PARTY: the SGLang cookbook for Nemotron 3 Super serves tool calls with `--tool-call-parser qwen3_coder` and uses `temperature=0.6`, `top_p=0.95` in its tool-calling example. This describes a self-hosted server, not Token Factory. https://docs.sglang.io/cookbook/autoregressive/NVIDIA/Nemotron3-Super
- Fallback if a model lacks native tool calling: ask for a JSON action via `response_format` and run the tool loop in the harness.

## Structured output

Source: https://docs.tokenfactory.nebius.com/ai-models-inference/json.md

- VERIFIED: `response_format` with `{"type": "json_object"}` (valid JSON, free fields) or `{"type": "json_schema"}` with a `json_schema` key. Support varies by model; look for the "JSON mode" tag on the model card.
- VERIFIED advice: put instructions and schema in the prompt as well as in `json_schema`; check `message.refusal` first; wrap `json.loads` in try/except.
- VERIFIED (2026-10-13, observed in smoke test): the schema must be wrapped. Both variants sent the same prompt, which also contains the schema, and the same schema (an object with `city` string, `country` string and `is_capital` boolean, all required, `additionalProperties: false`).
  - `json_wrapped` sends `{"type": "json_schema", "json_schema": {"name": "city_fact", "schema": <schema>, "strict": true}}`. On all four models the content parsed as JSON and passed pydantic validation.
  - `json_bare` sends `{"type": "json_schema", "json_schema": <schema>}`: the schema object directly under `json_schema`, with no `name`, `schema` or `strict`. All four models returned HTTP 422 with this detail (identical for all four):

    ```json
    {"detail": [{"type": "missing", "loc": ["body", "response_format", "json_schema", "name"], "msg": "Field required", "input": {"type": "object", "properties": {"city": {"type": "string"}, "country": {"type": "string"}, "is_capital": {"type": "boolean"}}, "required": ["city", "country", "is_capital"], "additionalProperties": false}}, {"type": "missing", "loc": ["body", "response_format", "json_schema", "schema"], "msg": "Field required", "input": {"type": "object", "properties": {"city": {"type": "string"}, "country": {"type": "string"}, "is_capital": {"type": "boolean"}}, "required": ["city", "country", "is_capital"], "additionalProperties": false}}]}
    ```
- Docs versus API (checked 2026-10-13 against the source page above): the page's Python example sends `"json_schema": Film.model_json_schema()` and its cURL example sends `"json_schema": '"$SCHEMA"'` with a bare schema in `SCHEMA`, which is the `json_bare` shape the API rejected. Only the page's "Example of a valid JSON schema" uses the wrapped `name` / `schema` / `strict` form. Recorded in `FEEDBACK.md`.
- UNVERIFIED: which Nemotron models carry the JSON mode tag on the console cards (not checked).
- Rule for the harness: always validate with pydantic after parsing, regardless of server-side enforcement.

## Rate limits

Source: https://docs.tokenfactory.nebius.com/ai-models-inference/rate-limits.md

- VERIFIED: the docs use an example baseline of 60 RPM and 400,000 TPM and say actual defaults are in the console's Rate Limits section. No concurrency limit and no per-model table on that page.
- VERIFIED scaling: if average usage in a 15-minute window is at least 80% of the limit, the next window's limit is multiplied by 1.2; at or below 50%, it is divided by 1.5; the ceiling is 20x base, beyond that an Enterprise plan.
- VERIFIED: exceeding the limit returns HTTP 429 with a `Retry-After` header (seconds). Some over-limit requests are still served and carry `x-ratelimit-over-limit: yes` as an early warning.
- VERIFIED headers: `x-ratelimit-limit-requests`, `x-ratelimit-limit-tokens`, `x-ratelimit-remaining-requests`, `x-ratelimit-remaining-tokens`, `x-ratelimit-reset-requests`, `x-ratelimit-reset-tokens`, `x-ratelimit-dynamic-scale-requests`, `x-ratelimit-dynamic-scale-tokens`, `x-ratelimit-dynamic-period-remaining`, `x-ratelimit-dynamic-period-usage-requests`, `x-ratelimit-dynamic-period-usage-tokens`.
- VERIFIED: the Batch API has significantly higher limits and is recommended for async work.
- VERIFIED (2026-10-13, observed in smoke test): per-model limits for this account, read from the `x-ratelimit-limit-*` response headers and stored in `config/rate_limits.json`. They may change (dynamic scaling applies).

  | Model | Requests per minute | Tokens per minute |
  |---|---|---|
  | Ultra | 300 | 200,000 |
  | Super | 300 | 200,000 |
  | Lightning | 600 | 400,000 |
  | Nano | 100 | 800,000 |

- Which call the headers come from: the script stores, for each model, the headers of the first call for that model that returned any `x-ratelimit-*` header. In this run that was the first call for every model, `plain_chat` (2,232 prompt tokens, `max_tokens` 600).
- After that call, remaining tokens were 2,537 below the limit on Nano and 2,538 below on the other three. This matches no model's prompt plus completion tokens for that call (Nano 2,506, Ultra 2,417, Lightning 2,832, Super 2,501). UNVERIFIED: what the token limit counts, and whether the limits are independent per model.
- Observed (2026-10-13, smoke test): the gap was about 2,538 on all four models, although completion tokens for that call ranged from 185 (Ultra) to 600 (Lightning). The counting rule stays UNVERIFIED.
- Observed (2026-10-13, smoke test): `x-ratelimit-reset-requests` and `x-ratelimit-reset-tokens` read "1s" on all 44 calls that returned rate-limit headers. Reading the limits as per minute comes from the Nebius docs (RPM and TPM), not from the headers.

Implication, from our assumed volumes (not measured): requests per minute is not the problem; tokens per minute is, and Ultra is the bottleneck. The per-model arithmetic is in ARCHITECTURE.md.

## Reasoning mode for Nemotron

- THIRD-PARTY (self-hosted Nemotron 3 Super, SGLang docs): reasoning is on by default; it is disabled with `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`. Token Factory also documents `reasoning_effort` (VERIFIED as a field).
- VERIFIED (2026-10-13, observed in smoke test): Token Factory accepted both controls on all four models (HTTP 200): `reasoning_effort` values `"none"`, `"low"` and `"high"`, and the `thinking_off` variant. `thinking_off` passes `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` to the OpenAI SDK, which sends `chat_template_kwargs` as a top-level field of the request body.
- VERIFIED (2026-10-13, observed in smoke test), one sample each on a trivial prompt ("A shop sells 3 pens for $2. How much do 12 pens cost? Reply with only the amount.", expected $8), so no quality conclusion:
  - `reasoning_effort: "none"` and `thinking_off` gave correct answers in 2 to 3 completion tokens on Ultra, Super and Lightning.
  - On Nano, `reasoning_effort: "none"` returned `content: null` (2 completion tokens) with the answer "8" in the `reasoning` field, so a caller reading `content` got an empty answer. `thinking_off` returned the correct answer "$8" in `content`.
  - `reasoning_effort` low and high showed no visible difference on Ultra (81 completion tokens each).
  - Observed (2026-10-13, smoke test), single sample: on Super, `reasoning_effort: "low"` used 45 completion tokens and `"high"` used 109, and low added 7 prompt tokens (48 instead of 41 for the same prompt). On Ultra the prompt stayed at 41 tokens for both.
- VERIFIED (2026-10-13, observed in smoke test): Lightning with reasoning on used all `max_tokens`=600 (`finish_reason: "length"`) in 6 of its 11 successful calls: `plain_chat`, `plain_chat_2`, `reason_default`, `effort_high`, `thinking_on`, `non_english`. In the first five, the thinking text came back in `content` (starting "Here's a thinking process:") and no final answer was produced. In `non_english`, the reasoning came back in separate `reasoning` and `reasoning_content` fields, and the Spanish answer in `content` was cut off mid-sentence. With `effort_low`, `effort_none` and `thinking_off` it ended normally (`finish_reason: "stop"`).
- Note on `runs/smoke_test.json`: the script's answer check marked `reason_default`, `effort_high` and `thinking_on` on Lightning as correct, because the truncated thinking text contains "8". Treat those three as failed.
- Why it matters: reasoning tokens are extra output tokens (likely billed) and add latency. Operators on cheap models should probably run with reasoning off or low; the director and auditor may need it. Test cost and quality both ways.

## Response handling

Observed (2026-10-13, smoke test), not conclusions:

- `content` can be null: on every `tool_call` response (all four models), and on Nano with `reasoning_effort: "none"`, where the answer "8" was in the `reasoning` field.
- Reasoning text arrives in different places per model. Ultra: `reasoning_content` only (9 calls). Nano: `reasoning` only (10 calls). Super: both `reasoning` and `reasoning_content`, with identical text (9 calls). Lightning: both fields, with identical text (3 calls), or untagged in `content`, starting "Here's a thinking process:" (5 calls, all cut off at `max_tokens`).
- So the harness must not assume `content` is non-null, must check `finish_reason`, and must read reasoning text from whichever field carries it, counting it once.

## Speed

- VERIFIED (2026-10-13, observed in smoke test): end-to-end output tokens per second (output tokens / total latency, including network and prompt processing). Median over calls with at least 100 output tokens.

  | Model | Median tok/s | Calls (n) | Listed in console |
  |---|---|---|---|
  | Ultra | 135.3 | 4 | 523 |
  | Super | 102.0 | 6 | 127 |
  | Lightning | 220.4 | 8 | 314.12 |
  | Nano | 131.7 | 9 | 60 |

- The listed console speeds were not reproduced (Nano measured faster than listed). Outputs were short (at most 600 tokens), so these are weak measurements. A long-output test is needed before using speeds in the plan.

## Skills on Nemotron

Observed on 2026-10-15 between 03:29 and 03:31 UTC (2026-10-14 local time) with `scripts/skill_check.py`, on the current skill text; raw results in `runs/skill_check.json` and the outputs in `runs/skill_check_outputs.md` (both gitignored). Setup: reasoning off (`chat_template_kwargs.enable_thinking: false`), wrapped json_schema, `max_tokens` 800, one small fixed input per skill, 3 calls with the skill and 3 without, 60 calls. Estimated spend from `config/prices.json`: USD 0.007564.

| Skill | Model | Prompt tokens without / with | Skill cost (tokens) | chars / 4 estimate | Completion tokens with (without) | Median latency s with (without) |
|---|---|---|---|---|---|---|
| prose-style | Lightning | 154 / 810 | 656 | 648 | 58 to 92 (57 to 75) | 0.89 (0.60) |
| prose-style | Ultra | 154 / 810 | 656 | 648 | 85 to 140 (63 to 115) | 1.60 (1.15) |
| minimal-code | Lightning | 143 / 705 | 562 | 636 | 114 to 179 (91 to 279) | 1.06 (1.34) |
| code-review | Lightning | 142 / 405 | 263 | 319 | 97 to 162 (67 to 95) | 1.01 (0.67) |
| testing-strategy | Lightning | 136 / 341 | 205 | 261 | 144 to 436 (125 to 135) | 1.36 (0.80) |
| debug | Lightning | 154 / 369 | 215 | 242 | 211 to 308 (102 to 110) | 1.22 (0.83) |
| deploy-checklist | Lightning | 140 / 365 | 225 | 274 | 260 to 296 (67 to 119) | 1.49 (0.69) |
| incident-triage | Lightning | 152 / 488 | 336 | 401 | 94 to 109 (64 to 82) | 0.75 (0.73) |
| status-update | Lightning | 158 / 536 | 378 | 448 | 66 to 108 (52 to 111) | 0.89 (0.72) |
| postmortem | Lightning | 155 / 607 | 452 | 563 | 216 to 279 (80 to 106) | 1.39 (0.69) |

- VERIFIED (2026-10-15, observed in skill check): all 60 calls ended with `finish_reason: "stop"`, and every content parsed as JSON, matched the schema and held a non-empty answer. None was wrapped in a markdown code fence. `reasoning_tokens` was 0 on every call. `cached_tokens` was absent on Lightning and 0 on Ultra.
- Prompt tokens were the same on all three repeats of each variant, so each skill cost is exact for that skill text on that model. Lightning and Ultra returned the same counts for prose-style.
- The chars / 4 estimate came out 1.2% below the measured cost for prose-style and 13% to 27% above it for the other eight skills.
- `config/skills.json` holds these costs, tied to a SHA-256 of each skill's text, and ceilings of the measured cost plus 20%, rounded up to a multiple of 50.
- Earlier runs the same night, superseded by the table: at 03:01 UTC on the skill text before a stop-slop cleanup (60 calls, all passed, USD 0.007834; costs within 7 tokens of the table), and at 03:26 UTC a run that stopped after 48 calls (all passed, USD 0.002488) when the script refused an edited skill's estimate against its old ceiling, since fixed. Total skill-check spend: USD 0.017886.
- Not measured: Super and Nano, reasoning on, other inputs or base prompts, and output quality. Completion tokens and latency are single small samples.

## First-call checklist (do this before writing agents)

1. Copy exact Nemotron model IDs from the console to `config/prices.json`.
2. Read real RPM and TPM from the console.
3. One plain chat call per model: confirm it works, read `usage`, compare against console billing. Repeat it once with the identical prompt and check `cached_tokens`. Record latency and output tokens per second to check the listed speeds.
4. One call with `tools` per model: does it return `tool_calls`? Does it support more than one call in a response?
5. One call with `response_format` json_schema per model, wrapped and bare schema.
6. One call with reasoning on and off (`reasoning_effort` and `extra_body`): compare tokens, latency, quality.
7. Test a short non-English prompt on Lightning and compare with Super.
8. Record every friction point in `FEEDBACK.md`.

## Streaming probe (2026-10-16 UTC, 2026-10-15 local time)

Observed with `scripts/stream_probe.py` (raw results in `runs/stream_probe.json`, gitignored). Per model, three streaming requests with `stream_options.include_usage: true`: `off` (reasoning off, max_tokens 48), `cancel` (reasoning off, max_tokens 64, closed by the client after 3 content chunks) and `on` (reasoning on via `chat_template_kwargs.enable_thinking: true`, max_tokens 256). One sample each. Estimated spend: USD 0.001192.

Summary across the four models (details per model below):

- VERIFIED: with `include_usage`, every model ended the stream with a JSON chunk that has `choices: []` and the final `usage`, then `data: [DONE]`. Events were separated by blank lines only (no comments, no `event:` lines).
- VERIFIED: Ultra and Nano also put running `usage` totals on every chunk (the role chunk shows `completion_tokens: 0`). Super and Lightning sent `usage` only on the final chunk. A running total seen before a stream is cut is a lower bound, not the final usage.
- VERIFIED: `completion_tokens_details.reasoning_tokens` was reported by Ultra, Super and Lightning (0 with reasoning off). Nano's usage had only `prompt_tokens`, `completion_tokens` and `total_tokens`.
- VERIFIED: `prompt_tokens_details.cached_tokens` was 0 on Ultra (final chunk only, not on the running chunks) and Super (with an extra `created_cache_tokens: 0`); `prompt_tokens_details` was null on Lightning and absent on Nano. Ultra, Super and Lightning also sent `prompt_cache_hit_tokens` (0) and `prompt_cache_miss_tokens` (equal to `prompt_tokens`), fields not in the docs.
- VERIFIED: the first chunk is a role chunk: `{"role": "assistant", "content": ""}` on Ultra, Super and Nano, `{"role": "assistant"}` with no `content` key on Lightning. `delta.content` was never null; it was absent on reasoning chunks and on Lightning's finish chunk (`delta: {}`).
- VERIFIED: reasoning deltas used `reasoning_content` on Ultra, `reasoning` on Nano, and both fields with identical text on Super and Lightning, as in the non-streaming smoke test.
- VERIFIED: Lightning with reasoning on hit `max_tokens` 256 (`finish_reason: "length"`, `reasoning_tokens` 256 of 256). It streamed the reasoning in both fields, then sent the same 758 characters once more as one `content` chunk. A client that reads only `content` gets the reasoning text as the answer.
- VERIFIED: `finish_reason` values seen: `stop` and `length`. Ultra, Super and Nano also sent `prompt_token_ids` and `prompt_text` (null, first chunk), `logprobs`, `token_ids` and `stop_reason` in choices, and `system_fingerprint` on the final chunk; Lightning's chunks had none of these.
- VERIFIED: closing the connection after 3 content chunks raised no error on the client. Ultra and Nano had delivered running usage before the close; Super and Lightning had delivered none.
- VERIFIED: streaming responses carry the `x-ratelimit-*` headers (`content-type: text/event-stream; charset=utf-8`). No `retry-after` on these HTTP 200 responses. After the `off` call (35 prompt tokens, `max_tokens` 48), `x-ratelimit-remaining-tokens` was the limit minus 65 on all four models. What the token limit counts stays UNVERIFIED.

- UNVERIFIED (client close): what the server does after the client closes the connection, and whether or how much it bills, is not observable from the client.
- UNVERIFIED: whether `retry-after` is sent on HTTP 429 for streaming requests (no 429 happened).

### nemotron-3-ultra

- VERIFIED (reasoning off): `usage` on every chunk (7 of 7) as running totals; the last JSON chunk has `choices: []` (True) and the final totals.
- VERIFIED (reasoning off): final usage `{"prompt_tokens": 35, "total_tokens": 56, "completion_tokens": 21, "prompt_tokens_details": {"cached_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 0}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 35}`.
- VERIFIED (reasoning off): 7 JSON chunks; delta keys `["content", "role"]`; first delta `{"role": "assistant", "content": ""}`; `finish_reason` values `["stop"]`.
- VERIFIED (reasoning off): `delta.content` "" in 1 chunk(s), null in 0, absent in 0; 20 content chars.
- VERIFIED (reasoning off): `[DONE]` seen: True; only blank lines between events (non-data lines `[]`); `"usage": null` chunks: 0.
- VERIFIED (reasoning on): `usage` on every chunk (25 of 25) as running totals; the last JSON chunk has `choices: []` (True) and the final totals.
- VERIFIED (reasoning on): final usage `{"prompt_tokens": 41, "total_tokens": 140, "completion_tokens": 99, "prompt_tokens_details": {"cached_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 95}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 41}`.
- VERIFIED (reasoning on): 25 JSON chunks; delta keys `["content", "reasoning_content", "role"]`; first delta `{"role": "assistant", "content": ""}`; `finish_reason` values `["stop"]`.
- VERIFIED (reasoning on): `delta.content` "" in 1 chunk(s), null in 0, absent in 21; 2 content chars.
- VERIFIED (reasoning on): reasoning text in delta field(s) `["reasoning_content"]`, chars `{"reasoning_content": 273}`.
- VERIFIED (reasoning on): `[DONE]` seen: True; only blank lines between events (non-data lines `[]`); `"usage": null` chunks: 0.
- VERIFIED (client close): closed after 4 JSON chunks; `usage` chunks received before the close: 4 (final `choices: []` chunk received: False); error raised by the close: `null`.
- VERIFIED (headers, `off` call): `retry-after` present: False; x-ratelimit headers `{"x-ratelimit-dynamic-period-remaining": "900s", "x-ratelimit-dynamic-period-usage-requests": "0%", "x-ratelimit-dynamic-period-usage-tokens": "0%", "x-ratelimit-dynamic-scale-requests": "1.00", "x-ratelimit-dynamic-scale-tokens": "1.00", "x-ratelimit-limit-requests": "300", "x-ratelimit-limit-tokens": "200000", "x-ratelimit-remaining-requests": "299", "x-ratelimit-remaining-tokens": "199935", "x-ratelimit-reset-requests": "1s", "x-ratelimit-reset-tokens": "1s"}`.

### nemotron-3-super

- VERIFIED (reasoning off): `usage` on 1 of 8 chunks; the last JSON chunk carries it: True; it has `choices: []`: True.
- VERIFIED (reasoning off): final usage `{"prompt_tokens": 35, "total_tokens": 56, "completion_tokens": 21, "prompt_tokens_details": {"cached_tokens": 0, "created_cache_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 0}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 35}`.
- VERIFIED (reasoning off): 8 JSON chunks; delta keys `["content", "role"]`; first delta `{"role": "assistant", "content": ""}`; `finish_reason` values `["stop"]`.
- VERIFIED (reasoning off): `delta.content` "" in 1 chunk(s), null in 0, absent in 0; 20 content chars.
- VERIFIED (reasoning off): `[DONE]` seen: True; only blank lines between events (non-data lines `[]`); `"usage": null` chunks: 0.
- VERIFIED (reasoning on): `usage` on 1 of 54 chunks; the last JSON chunk carries it: True; it has `choices: []`: True.
- VERIFIED (reasoning on): final usage `{"prompt_tokens": 41, "total_tokens": 176, "completion_tokens": 135, "prompt_tokens_details": {"cached_tokens": 0, "created_cache_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 131}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 41}`.
- VERIFIED (reasoning on): 54 JSON chunks; delta keys `["content", "reasoning", "reasoning_content", "role"]`; first delta `{"role": "assistant", "content": ""}`; `finish_reason` values `["stop"]`.
- VERIFIED (reasoning on): `delta.content` "" in 1 chunk(s), null in 0, absent in 51; 2 content chars.
- VERIFIED (reasoning on): reasoning text in delta field(s) `["reasoning", "reasoning_content"]`, chars `{"reasoning": 454, "reasoning_content": 454}` (identical text in each field).
- VERIFIED (reasoning on): `[DONE]` seen: True; only blank lines between events (non-data lines `[]`); `"usage": null` chunks: 0.
- VERIFIED (client close): closed after 4 JSON chunks; `usage` chunks received before the close: 0 (final `choices: []` chunk received: False); error raised by the close: `null`.
- VERIFIED (headers, `off` call): `retry-after` present: False; x-ratelimit headers `{"x-ratelimit-dynamic-period-remaining": "900s", "x-ratelimit-dynamic-period-usage-requests": "0%", "x-ratelimit-dynamic-period-usage-tokens": "0%", "x-ratelimit-dynamic-scale-requests": "1.00", "x-ratelimit-dynamic-scale-tokens": "1.00", "x-ratelimit-limit-requests": "300", "x-ratelimit-limit-tokens": "200000", "x-ratelimit-remaining-requests": "299", "x-ratelimit-remaining-tokens": "199935", "x-ratelimit-reset-requests": "1s", "x-ratelimit-reset-tokens": "1s"}`.

### nemotron-3.5-lightning

- VERIFIED (reasoning off): `usage` on 1 of 14 chunks; the last JSON chunk carries it: True; it has `choices: []`: True.
- VERIFIED (reasoning off): final usage `{"prompt_tokens": 35, "total_tokens": 56, "completion_tokens": 21, "prompt_tokens_details": null, "completion_tokens_details": {"reasoning_tokens": 0}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 35}`.
- VERIFIED (reasoning off): 14 JSON chunks; delta keys `["content", "role"]`; first delta `{"role": "assistant"}`; `finish_reason` values `["stop"]`.
- VERIFIED (reasoning off): `delta.content` "" in 0 chunk(s), null in 0, absent in 2; 20 content chars.
- VERIFIED (reasoning off): `[DONE]` seen: True; only blank lines between events (non-data lines `[]`); `"usage": null` chunks: 0.
- VERIFIED (reasoning on): `usage` on 1 of 142 chunks; the last JSON chunk carries it: True; it has `choices: []`: True.
- VERIFIED (reasoning on): final usage `{"prompt_tokens": 41, "total_tokens": 297, "completion_tokens": 256, "prompt_tokens_details": null, "completion_tokens_details": {"reasoning_tokens": 256}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 41}`.
- VERIFIED (reasoning on): 142 JSON chunks; delta keys `["content", "reasoning", "reasoning_content", "role"]`; first delta `{"role": "assistant"}`; `finish_reason` values `["length"]`.
- VERIFIED (reasoning on): `delta.content` "" in 0 chunk(s), null in 0, absent in 140; 758 content chars.
- VERIFIED (reasoning on): reasoning text in delta field(s) `["reasoning", "reasoning_content"]`, chars `{"reasoning": 758, "reasoning_content": 758}` (identical text in each field).
- VERIFIED (reasoning on): the content is the reasoning text again, sent as 1 content chunk(s) after the reasoning deltas.
- VERIFIED (reasoning on): `[DONE]` seen: True; only blank lines between events (non-data lines `[]`); `"usage": null` chunks: 0.
- VERIFIED (client close): closed after 4 JSON chunks; `usage` chunks received before the close: 0 (final `choices: []` chunk received: False); error raised by the close: `null`.
- VERIFIED (headers, `off` call): `retry-after` present: False; x-ratelimit headers `{"x-ratelimit-dynamic-period-remaining": "900s", "x-ratelimit-dynamic-period-usage-requests": "0%", "x-ratelimit-dynamic-period-usage-tokens": "0%", "x-ratelimit-dynamic-scale-requests": "1.00", "x-ratelimit-dynamic-scale-tokens": "1.00", "x-ratelimit-limit-requests": "600", "x-ratelimit-limit-tokens": "400000", "x-ratelimit-remaining-requests": "599", "x-ratelimit-remaining-tokens": "399935", "x-ratelimit-reset-requests": "1s", "x-ratelimit-reset-tokens": "1s"}`.

### nemotron-3-nano

- VERIFIED (reasoning off): `usage` on every chunk (23 of 23) as running totals; the last JSON chunk has `choices: []` (True) and the final totals.
- VERIFIED (reasoning off): final usage `{"prompt_tokens": 35, "total_tokens": 56, "completion_tokens": 21}`.
- VERIFIED (reasoning off): 23 JSON chunks; delta keys `["content", "role"]`; first delta `{"role": "assistant", "content": ""}`; `finish_reason` values `["stop"]`.
- VERIFIED (reasoning off): `delta.content` "" in 2 chunk(s), null in 0, absent in 0; 20 content chars.
- VERIFIED (reasoning off): `[DONE]` seen: True; only blank lines between events (non-data lines `[]`); `"usage": null` chunks: 0.
- VERIFIED (reasoning on): `usage` on every chunk (101 of 101) as running totals; the last JSON chunk has `choices: []` (True) and the final totals.
- VERIFIED (reasoning on): final usage `{"prompt_tokens": 41, "total_tokens": 142, "completion_tokens": 101}`.
- VERIFIED (reasoning on): 101 JSON chunks; delta keys `["content", "reasoning", "role"]`; first delta `{"role": "assistant", "content": ""}`; `finish_reason` values `["stop"]`.
- VERIFIED (reasoning on): `delta.content` "" in 2 chunk(s), null in 0, absent in 96; 2 content chars.
- VERIFIED (reasoning on): reasoning text in delta field(s) `["reasoning"]`, chars `{"reasoning": 280}`.
- VERIFIED (reasoning on): `[DONE]` seen: True; only blank lines between events (non-data lines `[]`); `"usage": null` chunks: 0.
- VERIFIED (client close): closed after 4 JSON chunks; `usage` chunks received before the close: 4 (final `choices: []` chunk received: False); error raised by the close: `null`.
- VERIFIED (headers, `off` call): `retry-after` present: False; x-ratelimit headers `{"x-ratelimit-dynamic-period-remaining": "900s", "x-ratelimit-dynamic-period-usage-requests": "0%", "x-ratelimit-dynamic-period-usage-tokens": "0%", "x-ratelimit-dynamic-scale-requests": "1.00", "x-ratelimit-dynamic-scale-tokens": "1.00", "x-ratelimit-limit-requests": "100", "x-ratelimit-limit-tokens": "800000", "x-ratelimit-remaining-requests": "99", "x-ratelimit-remaining-tokens": "799935", "x-ratelimit-reset-requests": "1s", "x-ratelimit-reset-tokens": "1s"}`.

## Reasoning token accounting (2026-10-16)

Checked without API calls on the saved streaming probe data (`runs/stream_probe.json`, the run in "Streaming probe" above).

- VERIFIED: on all eight streaming probe calls, `total_tokens` equals `prompt_tokens` plus `completion_tokens`.
- VERIFIED: `completion_tokens` includes the reasoning tokens on all four models.
  - Ultra, reasoning on: the running `completion_tokens` rose from 1 to 97 over 22 chunks that carried only reasoning text. Final: `completion_tokens` 99, `reasoning_tokens` 95, 2 characters of content.
  - Nano, reasoning on (no `reasoning_tokens` field): the running `completion_tokens` rose from 1 to 97 over 96 reasoning-only chunks. Final: `completion_tokens` 101, 2 characters of content.
  - Super, reasoning on: `completion_tokens` 135, `reasoning_tokens` 131, 2 characters of content. If the reasoning were not included, 135 completion tokens would have produced only 2 characters.
  - Lightning, reasoning on: `completion_tokens` 256 equals `reasoning_tokens` 256 equals `max_tokens`. The 758 characters of reasoning repeated as content (see the streaming probe) were not counted a second time.
- UNVERIFIED: whether Token Factory bills reasoning tokens at the output price. No console comparison yet.
- Consequence: the ledger bills `completion_tokens` as output, which already holds the reasoning, so reasoning is billed once. `call_cost` adds `reasoning_tokens` only when they exceed `completion_tokens`, which no observed call did. The cost code is unchanged; a regression test pins the Ultra numbers above.

## Tool-calling probe (2026-10-16)

Observed with `scripts/tool_probe.py` (raw results in `runs/tool_probe.json`, gitignored), streaming with `include_usage`, one function tool `add(a, b)`. Calls per model: `auto` (`tool_choice: "auto"`, reasoning off), `forced` (`tool_choice` naming the function), `reasoning_on`, `with_schema` (tools plus a wrapped json_schema `response_format`), `follow_up` (the tool call and a `tool` message with the result, only after a tool call in `auto`) and `json_action` (no tools, the JSON action protocol with `response_format: json_object`). One sample each. Estimated spend: USD 0.003598.

Summary across the four models (details per model below):

- VERIFIED: all four accepted `tools` with `tool_choice: "auto"` and with `tool_choice` naming the function (HTTP 200, streaming).
- VERIFIED: Ultra, Super and Lightning returned a tool call in `auto`, `forced` and `reasoning_on`, with `finish_reason: "tool_calls"` and arguments that parse as JSON (`{"a": 17, "b": 25}`). In `follow_up` (the tool call plus a `tool` message with the result) all three answered in text with `finish_reason: "stop"`.
- VERIFIED: streamed tool-call fragments. The first fragment carries `index`, `id`, `type` and `function.name`, with `function.arguments` null (Ultra, Super, Lightning), "" (Nano) or the whole arguments string (Ultra `forced`, Nano `forced`). Later fragments carry `index` and an `arguments` piece only; Lightning sent the arguments in one piece. Ids looked like `chatcmpl-tool-...` (Ultra, Super, Nano `forced`) or `call_...` (Lightning, Nano).
- VERIFIED: Super's `auto` reply had text content ("I need to use the add tool ...") before the tool call in the same response.
- VERIFIED: Nano was unreliable. `auto` worked. `forced` returned a tool call with `finish_reason: "stop"`. `reasoning_on` returned arguments that do not parse (the pieces `{`, `"a": 17`, `{}`). `follow_up` called the tool again (with text) instead of answering. A late fragment repeated the `id` and `type` keys with a null id.
- VERIFIED: with a wrapped json_schema `response_format` sent together with `tools`, none of the four called the tool; each answered `{"sum": 42}` directly with `finish_reason: "stop"`. On this sample, structured output and native tool calls do not combine in one call.
- VERIFIED: the JSON action protocol (no tools, `response_format: {"type": "json_object"}`) gave exactly `{"action": "tool", "name": "add", "args": {"a": 17, "b": 25}}` on all four.
- Decision, set in `config/harness.json` (`loop_protocol` per model): `native_tools` for Ultra, Super and Lightning, `json_protocol` for Nano. `json_protocol` is the baseline the loop always supports. One sample per call, so this is weak evidence; the benchmark should confirm it.
- UNVERIFIED: parallel tool calls in one response, tools with more than one function, and long tool results.

### nemotron-3-ultra

- VERIFIED (`auto`): HTTP 200; `finish_reason` `["tool_calls"]`.
- VERIFIED (`auto`): assembled tool calls `[{"index": 0, "id": "chatcmpl-tool-a2e7401fbb9aa538", "name": "add", "args": {"a": 17, "b": 25}, "args_parsed": true}]`.
- VERIFIED (`auto`): 4 `delta.tool_calls` fragment(s); first ones `[{"keys": ["function", "id", "index", "type"], "index": 0, "id": "chatcmpl-tool-a2e7401fbb9aa538", "name": "add", "arguments": null}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "{\"a\": "}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "17, \"b\": "}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "25}"}]`.
- VERIFIED (`auto`): final usage `{"prompt_tokens": 345, "total_tokens": 379, "completion_tokens": 34, "prompt_tokens_details": {"cached_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 0}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 345}`.
- VERIFIED (`forced`): HTTP 200; `finish_reason` `["tool_calls"]`.
- VERIFIED (`forced`): assembled tool calls `[{"index": 0, "id": "chatcmpl-tool-aecf01287bdd6c48", "name": "add", "args": {"a": 17, "b": 25}, "args_parsed": true}]`.
- VERIFIED (`forced`): 1 `delta.tool_calls` fragment(s); first ones `[{"keys": ["function", "id", "index", "type"], "index": 0, "id": "chatcmpl-tool-aecf01287bdd6c48", "name": "add", "arguments": "{\"a\": 17, \"b\": 25}"}]`.
- VERIFIED (`forced`): final usage `{"prompt_tokens": 345, "total_tokens": 364, "completion_tokens": 19, "prompt_tokens_details": {"cached_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 0}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 345}`.
- VERIFIED (`reasoning_on`): HTTP 200; `finish_reason` `["tool_calls"]`.
- VERIFIED (`reasoning_on`): assembled tool calls `[{"index": 0, "id": "chatcmpl-tool-8231cfae333ffd77", "name": "add", "args": {"a": 17, "b": 25}, "args_parsed": true}]`.
- VERIFIED (`reasoning_on`): 4 `delta.tool_calls` fragment(s); first ones `[{"keys": ["function", "id", "index", "type"], "index": 0, "id": "chatcmpl-tool-8231cfae333ffd77", "name": "add", "arguments": null}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "{\"a\": "}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "17, \"b\": "}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "25}"}]`.
- VERIFIED (`reasoning_on`): 109 reasoning characters.
- VERIFIED (`reasoning_on`): final usage `{"prompt_tokens": 345, "total_tokens": 417, "completion_tokens": 72, "prompt_tokens_details": {"cached_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 37}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 345}`.
- VERIFIED (`with_schema`): HTTP 200; `finish_reason` `["stop"]`.
- VERIFIED (`with_schema`): no `delta.tool_calls` fragments.
- VERIFIED (`with_schema`): content `"{\"sum\": 42}"`.
- VERIFIED (`with_schema`): final usage `{"prompt_tokens": 353, "total_tokens": 361, "completion_tokens": 8, "prompt_tokens_details": {"cached_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 0}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 353}`.
- VERIFIED (`follow_up`): HTTP 200; `finish_reason` `["stop"]`.
- VERIFIED (`follow_up`): no `delta.tool_calls` fragments.
- VERIFIED (`follow_up`): content `"The result of 17 + 25 is **42**."`.
- VERIFIED (`follow_up`): final usage `{"prompt_tokens": 398, "total_tokens": 414, "completion_tokens": 16, "prompt_tokens_details": {"cached_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 0}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 398}`.
- VERIFIED (`json_action`): HTTP 200; `finish_reason` `["stop"]`.
- VERIFIED (`json_action`): no `delta.tool_calls` fragments.
- VERIFIED (`json_action`): content `"{\"action\": \"tool\", \"name\": \"add\", \"args\": {\"a\": 17, \"b\": 25}}"`.
- VERIFIED (`json_action`): final usage `{"prompt_tokens": 111, "total_tokens": 141, "completion_tokens": 30, "prompt_tokens_details": {"cached_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 0}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 111}`.

### nemotron-3-super

- VERIFIED (`auto`): HTTP 200; `finish_reason` `["tool_calls"]`.
- VERIFIED (`auto`): assembled tool calls `[{"index": 0, "id": "chatcmpl-tool-89d7c9b91f22cceb", "name": "add", "args": {"a": 17, "b": 25}, "args_parsed": true}]`.
- VERIFIED (`auto`): 4 `delta.tool_calls` fragment(s); first ones `[{"keys": ["function", "id", "index", "type"], "index": 0, "id": "chatcmpl-tool-89d7c9b91f22cceb", "name": "add", "arguments": null}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "{\"a\": "}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "17, \"b\": "}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "25}"}]`.
- VERIFIED (`auto`): content `"I need to use the add tool to calculate 17 + 25 as requested."`.
- VERIFIED (`auto`): final usage `{"prompt_tokens": 392, "total_tokens": 444, "completion_tokens": 52, "prompt_tokens_details": {"cached_tokens": 0, "created_cache_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 0}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 392}`.
- VERIFIED (`forced`): HTTP 200; `finish_reason` `["tool_calls"]`.
- VERIFIED (`forced`): assembled tool calls `[{"index": 0, "id": "chatcmpl-tool-9315f67ab9b88f06", "name": "add", "args": {"a": 17, "b": 25}, "args_parsed": true}]`.
- VERIFIED (`forced`): 4 `delta.tool_calls` fragment(s); first ones `[{"keys": ["function", "id", "index", "type"], "index": 0, "id": "chatcmpl-tool-9315f67ab9b88f06", "name": "add", "arguments": null}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "{\"a\": "}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "17, \"b\": "}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "25}"}]`.
- VERIFIED (`forced`): final usage `{"prompt_tokens": 392, "total_tokens": 424, "completion_tokens": 32, "prompt_tokens_details": {"cached_tokens": 0, "created_cache_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 0}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 392}`.
- VERIFIED (`reasoning_on`): HTTP 200; `finish_reason` `["tool_calls"]`.
- VERIFIED (`reasoning_on`): assembled tool calls `[{"index": 0, "id": "chatcmpl-tool-81c76bd826511980", "name": "add", "args": {"a": 17, "b": 25}, "args_parsed": true}]`.
- VERIFIED (`reasoning_on`): 4 `delta.tool_calls` fragment(s); first ones `[{"keys": ["function", "id", "index", "type"], "index": 0, "id": "chatcmpl-tool-81c76bd826511980", "name": "add", "arguments": null}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "{\"a\": "}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "17, \"b\": "}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "25}"}]`.
- VERIFIED (`reasoning_on`): 36 reasoning characters.
- VERIFIED (`reasoning_on`): final usage `{"prompt_tokens": 392, "total_tokens": 443, "completion_tokens": 51, "prompt_tokens_details": {"cached_tokens": 0, "created_cache_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 16}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 392}`.
- VERIFIED (`with_schema`): HTTP 200; `finish_reason` `["stop"]`.
- VERIFIED (`with_schema`): no `delta.tool_calls` fragments.
- VERIFIED (`with_schema`): content `"{\"sum\": 42}"`.
- VERIFIED (`with_schema`): final usage `{"prompt_tokens": 400, "total_tokens": 408, "completion_tokens": 8, "prompt_tokens_details": {"cached_tokens": 0, "created_cache_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 0}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 400}`.
- VERIFIED (`follow_up`): HTTP 200; `finish_reason` `["stop"]`.
- VERIFIED (`follow_up`): no `delta.tool_calls` fragments.
- VERIFIED (`follow_up`): content `"The result of adding 17 and 25 is **42**."`.
- VERIFIED (`follow_up`): final usage `{"prompt_tokens": 445, "total_tokens": 462, "completion_tokens": 17, "prompt_tokens_details": {"cached_tokens": 0, "created_cache_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 0}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 445}`.
- VERIFIED (`json_action`): HTTP 200; `finish_reason` `["stop"]`.
- VERIFIED (`json_action`): no `delta.tool_calls` fragments.
- VERIFIED (`json_action`): content `"{\"action\": \"tool\", \"name\": \"add\", \"args\": {\"a\": 17, \"b\": 25}}"`.
- VERIFIED (`json_action`): final usage `{"prompt_tokens": 111, "total_tokens": 141, "completion_tokens": 30, "prompt_tokens_details": {"cached_tokens": 0, "created_cache_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 0}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 111}`.

### nemotron-3.5-lightning

- VERIFIED (`auto`): HTTP 200; `finish_reason` `["tool_calls"]`.
- VERIFIED (`auto`): assembled tool calls `[{"index": 0, "id": "call_c8c86247be164a498087ace4", "name": "add", "args": {"a": 17, "b": 25}, "args_parsed": true}]`.
- VERIFIED (`auto`): 2 `delta.tool_calls` fragment(s); first ones `[{"keys": ["function", "id", "index", "type"], "index": 0, "id": "call_c8c86247be164a498087ace4", "name": "add", "arguments": null}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "{\"a\":17,\"b\":25}"}]`.
- VERIFIED (`auto`): final usage `{"prompt_tokens": 439, "total_tokens": 473, "completion_tokens": 34, "prompt_tokens_details": null, "completion_tokens_details": {"reasoning_tokens": 0}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 439}`.
- VERIFIED (`forced`): HTTP 200; `finish_reason` `["tool_calls"]`.
- VERIFIED (`forced`): assembled tool calls `[{"index": 0, "id": "call_f387ce9385b44f15811fda4e", "name": "add", "args": {"a": 17, "b": 25}, "args_parsed": true}]`.
- VERIFIED (`forced`): 2 `delta.tool_calls` fragment(s); first ones `[{"keys": ["function", "id", "index", "type"], "index": 0, "id": "call_f387ce9385b44f15811fda4e", "name": "add", "arguments": null}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "{\"a\":17,\"b\":25}"}]`.
- VERIFIED (`forced`): final usage `{"prompt_tokens": 317, "total_tokens": 351, "completion_tokens": 34, "prompt_tokens_details": null, "completion_tokens_details": {"reasoning_tokens": 0}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 317}`.
- VERIFIED (`reasoning_on`): HTTP 200; `finish_reason` `["tool_calls"]`.
- VERIFIED (`reasoning_on`): assembled tool calls `[{"index": 0, "id": "call_f532a7ef98dc4dd5a9cdfac6", "name": "add", "args": {"a": 17, "b": 25}, "args_parsed": true}]`.
- VERIFIED (`reasoning_on`): 2 `delta.tool_calls` fragment(s); first ones `[{"keys": ["function", "id", "index", "type"], "index": 0, "id": "call_f532a7ef98dc4dd5a9cdfac6", "name": "add", "arguments": null}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "{\"a\":17,\"b\":25}"}]`.
- VERIFIED (`reasoning_on`): 63 reasoning characters.
- VERIFIED (`reasoning_on`): final usage `{"prompt_tokens": 439, "total_tokens": 493, "completion_tokens": 54, "prompt_tokens_details": null, "completion_tokens_details": {"reasoning_tokens": 19}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 439}`.
- VERIFIED (`with_schema`): HTTP 200; `finish_reason` `["stop"]`.
- VERIFIED (`with_schema`): no `delta.tool_calls` fragments.
- VERIFIED (`with_schema`): content `"{\"sum\": 42}"`.
- VERIFIED (`with_schema`): final usage `{"prompt_tokens": 447, "total_tokens": 455, "completion_tokens": 8, "prompt_tokens_details": null, "completion_tokens_details": {"reasoning_tokens": 0}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 447}`.
- VERIFIED (`follow_up`): HTTP 200; `finish_reason` `["stop"]`.
- VERIFIED (`follow_up`): no `delta.tool_calls` fragments.
- VERIFIED (`follow_up`): content `"The sum of 17 and 25 is 42."`.
- VERIFIED (`follow_up`): final usage `{"prompt_tokens": 492, "total_tokens": 508, "completion_tokens": 16, "prompt_tokens_details": null, "completion_tokens_details": {"reasoning_tokens": 0}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 492}`.
- VERIFIED (`json_action`): HTTP 200; `finish_reason` `["stop"]`.
- VERIFIED (`json_action`): no `delta.tool_calls` fragments.
- VERIFIED (`json_action`): content `"{\"action\": \"tool\", \"name\": \"add\", \"args\": {\"a\": 17, \"b\": 25}}"`.
- VERIFIED (`json_action`): final usage `{"prompt_tokens": 111, "total_tokens": 141, "completion_tokens": 30, "prompt_tokens_details": null, "completion_tokens_details": {"reasoning_tokens": 0}, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 111}`.

### nemotron-3-nano

- VERIFIED (`auto`): HTTP 200; `finish_reason` `["tool_calls"]`.
- VERIFIED (`auto`): assembled tool calls `[{"index": 0, "id": "call_55ae1cd829e8412d8671a445", "name": "add", "args": {"a": 17, "b": 25}, "args_parsed": true}]`.
- VERIFIED (`auto`): 4 `delta.tool_calls` fragment(s); first ones `[{"keys": ["function", "id", "index", "type"], "index": 0, "id": "call_55ae1cd829e8412d8671a445", "name": "add", "arguments": ""}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "{"}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "\"a\": 17, \"b\": 25"}, {"keys": ["function", "id", "index", "type"], "index": 0, "id": null, "name": null, "arguments": "}"}]`.
- VERIFIED (`auto`): content `""`.
- VERIFIED (`auto`): final usage `{"prompt_tokens": 310, "total_tokens": 344, "completion_tokens": 34}`.
- VERIFIED (`forced`): HTTP 200; `finish_reason` `["stop"]`.
- VERIFIED (`forced`): assembled tool calls `[{"index": 0, "id": "chatcmpl-tool-83d2a8a6058b7508", "name": "add", "args": {"a": 17, "b": 25}, "args_parsed": true}]`.
- VERIFIED (`forced`): 4 `delta.tool_calls` fragment(s); first ones `[{"keys": ["function", "id", "index", "type"], "index": 0, "id": "chatcmpl-tool-83d2a8a6058b7508", "name": "add", "arguments": "{\n  \"a"}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "\": 17,\n"}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "  \"b\":"}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": " 25\n}"}]`.
- VERIFIED (`forced`): final usage `{"prompt_tokens": 310, "total_tokens": 329, "completion_tokens": 19}`.
- VERIFIED (`reasoning_on`): HTTP 200; `finish_reason` `["tool_calls"]`.
- VERIFIED (`reasoning_on`): assembled tool calls `[{"index": 0, "id": "call_cf6508a637b94a788ad62a79", "name": "add", "args": null, "args_parsed": false}]`.
- VERIFIED (`reasoning_on`): 4 `delta.tool_calls` fragment(s); first ones `[{"keys": ["function", "id", "index", "type"], "index": 0, "id": "call_cf6508a637b94a788ad62a79", "name": "add", "arguments": ""}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "{"}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "\"a\": 17"}, {"keys": ["function", "id", "index", "type"], "index": 0, "id": null, "name": null, "arguments": "{}"}]`.
- VERIFIED (`reasoning_on`): content `""`.
- VERIFIED (`reasoning_on`): 458 reasoning characters.
- VERIFIED (`reasoning_on`): final usage `{"prompt_tokens": 310, "total_tokens": 460, "completion_tokens": 150}`.
- VERIFIED (`with_schema`): HTTP 200; `finish_reason` `["stop"]`.
- VERIFIED (`with_schema`): no `delta.tool_calls` fragments.
- VERIFIED (`with_schema`): content `"{ \"sum\": 42 }"`.
- VERIFIED (`with_schema`): final usage `{"prompt_tokens": 318, "total_tokens": 329, "completion_tokens": 11}`.
- VERIFIED (`follow_up`): HTTP 200; `finish_reason` `["tool_calls"]`.
- VERIFIED (`follow_up`): assembled tool calls `[{"index": 0, "id": "call_54b385f3edaa4877803f8b08", "name": "add", "args": {"a": 17, "b": 25}, "args_parsed": true}]`.
- VERIFIED (`follow_up`): 5 `delta.tool_calls` fragment(s); first ones `[{"keys": ["function", "id", "index", "type"], "index": 0, "id": "call_54b385f3edaa4877803f8b08", "name": "add", "arguments": ""}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "{"}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": "\"a\": 17"}, {"keys": ["function", "index"], "index": 0, "id": null, "name": null, "arguments": ", \"b\": 25"}]`.
- VERIFIED (`follow_up`): content `"The sum of 17 and 25 is **42**. Here's the breakdown using the `add` tool:"`.
- VERIFIED (`follow_up`): final usage `{"prompt_tokens": 363, "total_tokens": 424, "completion_tokens": 61}`.
- VERIFIED (`json_action`): HTTP 200; `finish_reason` `["stop"]`.
- VERIFIED (`json_action`): no `delta.tool_calls` fragments.
- VERIFIED (`json_action`): content `"{\"action\": \"tool\", \"name\": \"add\", \"args\": {\"a\": 17, \"b\": 25}}"`.
- VERIFIED (`json_action`): final usage `{"prompt_tokens": 111, "total_tokens": 141, "completion_tokens": 30}`.
