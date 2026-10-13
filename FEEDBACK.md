# Feedback log (Nebius Token Factory and NVIDIA Nemotron)

Kept from day one for the hackathon feedback requirement. One entry per finding: date, what happened, what would help.

## 2026-10-12
- Docs: the function calling page lists no supported models and does not mention Nemotron. Could not tell from the docs whether Nemotron models support `tools`.
- Docs: the quickstart does not cover rate limits, tool calling, or JSON mode; they live on separate pages that are easy to miss.
- Docs: the rate limits page gives an example baseline (60 RPM, 400,000 TPM) and says real defaults are in the console. A per-model table in the docs would help.
- Console: model cards show price and speed clearly. Exact API model IDs for Nemotron are not shown on the same card (to confirm).
