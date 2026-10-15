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
