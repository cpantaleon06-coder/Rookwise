# Harness research: Nebius Token Factory and Nemotron

Researched October 12, 2026 from the official Token Factory docs and one third-party source. Each item is marked VERIFIED (read in the docs), THIRD-PARTY (not from Nebius), or UNVERIFIED (must be tested with a real call).

## API basics

| Item | Status | Detail |
|---|---|---|
| Base URL | VERIFIED | `https://api.tokenfactory.nebius.com/v1/` |
| Chat endpoint | VERIFIED | `POST https://api.tokenfactory.nebius.com/v1/chat/completions` |
| Auth | VERIFIED | `Authorization: Bearer <key>`; key shown once in the console; do not expose in client-side code |
| OpenAI compatibility | VERIFIED | Official docs use the standard OpenAI Python and JS SDKs with a custom base URL and `NEBIUS_API_KEY` |
| Nemotron model IDs | UNVERIFIED | Not on the docs pages read. Copy them from the console model cards into `config/prices.json` |

Sources: https://docs.tokenfactory.nebius.com/quickstart.md and https://docs.tokenfactory.nebius.com/api-reference/introduction.md

## Request and response fields

Source: https://docs.tokenfactory.nebius.com/api-reference/inference/create-chat-completion.md

- VERIFIED request fields: `model`, `messages` (required); `max_tokens`, `max_completion_tokens`, `temperature`, `top_p`, `n`, `stop`, `presence_penalty`, `frequency_penalty`, `logit_bias`; `tools`, `tool_choice`; `response_format`; `reasoning_effort`; `stream`, `stream_options`; `logprobs`, `top_logprobs`; `store`, `user`, `service_tier`, `extra_body`.
- VERIFIED response: `id`, `object`, `created`, `model`, `choices`, `usage`, `service_tier`.
- VERIFIED usage fields: `prompt_tokens`, `completion_tokens`, `total_tokens`, `prompt_tokens_details.cached_tokens`, `completion_tokens_details.reasoning_tokens`.
- VERIFIED streaming: `usage` is populated only with `stream_options.include_usage`.
- Open question: whether reasoning tokens are billed as output tokens. UNVERIFIED. The ledger must read the billed usage, and the first real call should compare it with the console.

## Tool calling

Source: https://docs.tokenfactory.nebius.com/ai-models-inference/function-calling.md

- VERIFIED: OpenAI-style. Request has `tools` (type `function`, with `name`, `description`, JSON Schema `parameters`) and optional `tool_choice` (`"auto"` default, or a forced function). Response message carries `tool_calls` with `id`, `type`, and `function.name` and `function.arguments` (a JSON string). The caller executes the function and appends a message with `role: "tool"`, the matching `tool_call_id` and the function `name`.
- UNVERIFIED: which models support it. The page lists no models and the only example model is a Llama. Nemotron is not mentioned.
- UNVERIFIED: parallel tool calls.
- THIRD-PARTY: the SGLang cookbook for Nemotron 3 Super serves tool calls with `--tool-call-parser qwen3_coder` and uses `temperature=0.6`, `top_p=0.95` in its tool-calling example. This describes a self-hosted server, not Token Factory. https://docs.sglang.io/cookbook/autoregressive/NVIDIA/Nemotron3-Super
- Fallback if a model lacks native tool calling: ask for a JSON action via `response_format` and run the tool loop in the harness.

## Structured output

Source: https://docs.tokenfactory.nebius.com/ai-models-inference/json.md

- VERIFIED: `response_format` with `{"type": "json_object"}` (valid JSON, free fields) or `{"type": "json_schema"}` with a `json_schema` key. Support varies by model; look for the "JSON mode" tag on the model card.
- VERIFIED advice: put instructions and schema in the prompt as well as in `json_schema`; check `message.refusal` first; wrap `json.loads` in try/except.
- UNVERIFIED: whether the schema must be wrapped in `{name, schema, strict}` or passed bare (the docs examples disagree). Test on the target model.
- UNVERIFIED: which Nemotron models carry the JSON mode tag.
- Rule for the harness: always validate with pydantic after parsing, regardless of server-side enforcement.

## Rate limits

Source: https://docs.tokenfactory.nebius.com/ai-models-inference/rate-limits.md

- VERIFIED: the docs use an example baseline of 60 RPM and 400,000 TPM and say actual defaults are in the console's Rate Limits section. No concurrency limit and no per-model table on that page.
- VERIFIED scaling: if average usage in a 15-minute window is at least 80% of the limit, the next window's limit is multiplied by 1.2; at or below 50%, it is divided by 1.5; the ceiling is 20x base, beyond that an Enterprise plan.
- VERIFIED: exceeding the limit returns HTTP 429 with a `Retry-After` header (seconds). Some over-limit requests are still served and carry `x-ratelimit-over-limit: yes` as an early warning.
- VERIFIED headers: `x-ratelimit-limit-requests`, `x-ratelimit-limit-tokens`, `x-ratelimit-remaining-requests`, `x-ratelimit-remaining-tokens`, `x-ratelimit-reset-requests`, `x-ratelimit-reset-tokens`, `x-ratelimit-dynamic-scale-requests`, `x-ratelimit-dynamic-scale-tokens`, `x-ratelimit-dynamic-period-remaining`, `x-ratelimit-dynamic-period-usage-requests`, `x-ratelimit-dynamic-period-usage-tokens`.
- VERIFIED: the Batch API has significantly higher limits and is recommended for async work.
- TODO (user): read the real RPM and TPM for your account in the console and write them here.

Implication, from our assumed volumes (not measured): one run is about 27 requests and 441,000 tokens. Requests per minute is not the problem; tokens per minute probably is.

## Reasoning mode for Nemotron

- THIRD-PARTY (self-hosted Nemotron 3 Super, SGLang docs): reasoning is on by default; it is disabled with `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`. Whether Token Factory accepts that field is UNVERIFIED. Token Factory documents `reasoning_effort` instead (VERIFIED as a field; accepted values and Nemotron behavior UNVERIFIED).
- Why it matters: reasoning tokens are extra output tokens (likely billed) and add latency. Operators on cheap models should probably run with reasoning off or low; the director and auditor may need it. Test cost and quality both ways.

## First-call checklist (do this before writing agents)

1. Copy exact Nemotron model IDs from the console to `config/prices.json`.
2. Read real RPM and TPM from the console.
3. One plain chat call per model: confirm it works, read `usage`, compare against console billing.
4. One call with `tools` per model: does it return `tool_calls`? Does it support more than one call in a response?
5. One call with `response_format` json_schema per model, wrapped and bare schema.
6. One call with reasoning on and off (`reasoning_effort` and `extra_body`): compare tokens, latency, quality.
7. Test a short non-English prompt on Lightning and compare with Super.
8. Record every friction point in `FEEDBACK.md`.
