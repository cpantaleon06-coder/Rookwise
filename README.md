# Rookwise
# Rookwise

Rookwise investigates operational incidents for small teams that have no dedicated SRE, under a hard budget the user sets before the run. Cheap models read the logs in slices, a strong model judges, deterministic code checks every cited line, an independent auditor reviews the result, and a human decides. In v1 Rookwise only reads and recommends: it executes nothing.

Built for the Nebius x NVIDIA Global AI Hackathon 2026 on NVIDIA Nemotron models served by Nebius Token Factory.

> Status: draft written on 2026-10-25. Every number in the "Results" section is filled only from measured runs in `benchmarks/results/`. Anything marked TBD has not been measured yet.

## The problem

When a service breaks at 3 a.m., nobody on a small team has time to read 20,000 log lines across three services. An agent could, but a team has two reasons not to trust one:

1. **Trust.** An agent can state a root cause with confidence and cite log lines that do not exist.
2. **Cost.** An agent run has no price tag up front. The bill arrives after the run.

## What Rookwise does about it

- **Every claim cites a line, and code checks it.** Each claim in a diagnosis cites a source, a line range and an exact quote. `core/evidence.py` (no model involved) verifies that the source exists, the lines exist and the quote is really there (after whitespace normalization only). A claim is supported only if all of its citations pass. Claims that fail are withdrawn from the diagnosis, shown with their reason, and never hidden.
- **A budget set before the run.** A ledger reserves money before every model call and refuses calls that do not fit, so a run cannot pass its cap through retries or rounding. Money is exact (integer micro-USD). Every run reports predicted versus real cost.
- **Cheap models read, a strong model judges.** The volume goes to the cheapest model; the strong model only sees consolidated findings.
- **An independent auditor and a human.** A separate model context reviews the supported claims against a fixed rubric. A person approves or rejects the recommendation.
- **Honest about what it did not read.** The report lists unread slices.

Verified citations mean the evidence exists. They do not prove the diagnosis is correct, which is why accuracy is measured separately (see "Results").

## How it works

1. **Intake.** The user picks the evidence (logs, metrics, deploy diff, runbook, ticket) and sets the USD cap.
2. **Plan.** The director reads the ticket, the runbook and an inventory of the sources and plans the investigation as blocks of tasks.
3. **Read.** Operators each read one slice of the evidence (slices are cut deterministically, with absolute line numbers) and return findings with citations.
4. **Consolidate.** One manager per block merges its operators' findings.
5. **Judge.** The director writes the diagnosis: root cause, category, supporting claims and a remediation plan.
6. **Verify.** Deterministic code checks every citation. Unsupported claims are withdrawn.
7. **Audit.** The auditor reviews what remains. If nothing supported remains, the result is inconclusive and no audit call is made.
8. **Approve.** The human reads the diagnosis, the evidence check, the audit and the cost report.

If an operator fails, the harness retries with backoff, repairs invalid output with the exact validation error, and escalates to the next model on a ladder. Every step is recorded.

## How we use NVIDIA Nemotron and Nebius Token Factory

Every model call in Rookwise goes to the Nebius Token Factory chat completions API (OpenAI-compatible) through one harness. All models are NVIDIA Nemotron:

| Level | Model | Why |
|---|---|---|
| Director (plan, diagnosis) | Nemotron-3-Ultra-550b-a55b | Judgment over consolidated findings |
| Auditor | Nemotron-3-Ultra-550b-a55b | Independent review in a separate context |
| Managers, escalation of failed tasks | Nemotron-3-Super-120b-a12b | Consolidation, second try |
| Operators | Nemotron-3.5-Lightning | Reads the volume at low cost |

Token Factory prices (per 1M tokens, input / output, read from the console on 2026-10-12): Ultra 1.00 / 3.00, Super 0.30 / 0.90, Lightning 0.06 / 0.24. Ultra costs about 16.7 times Lightning per input token, which is why the cheap model reads the volume. Prices live in `config/prices.json` and are never hard-coded.

What Token Factory made possible: one OpenAI-compatible endpoint for four Nemotron sizes lets a run mix a 550B-class director with small operators and price every call per token, so the ledger can reserve money before each call. Rate limits per model are read from the `x-ratelimit-*` headers and stored in `config/rate_limits.json`. We also tested structured outputs (`json_schema`) and reasoning controls; what we found is written up in `FEEDBACK.md` and `docs/HARNESS_RESEARCH.md`.

Tavily: operators have a web search tool for error signatures and advisories. <!-- FILL: say whether a product run used it. As of 2026-10-25 it is built but not used in a run. -->

## Quick start

Requirements: Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/cpantaleon06-coder/rookwise.git
cd rookwise
uv sync --frozen --all-extras
uv run --frozen python scripts/gen_incidents.py     # rebuilds the synthetic incident logs (deterministic)
uv run --frozen python -m pytest -q                 # tests, no network
uv run --frozen python scripts/run_incident.py inc-01 estimate   # full pipeline on a stub, no network, no cost
```

The estimate run plays every agent with a stub transport, so the ledger, the slicing and every budget rule run for real, and the report shows which calls the ledger would refuse. It costs nothing.

### A real run (costs credits)

```bash
cp .env.example .env          # then set NEBIUS_API_KEY
HARNESS_MODE=record uv run --frozen python scripts/run_incident.py inc-01 record \
  --run-usd 0.50 --approve-cap 0.50 --cassette runs/cassettes/inc-01.demo.json
```

On Windows PowerShell set the variable first: `$env:HARNESS_MODE = "record"`. The command refuses to start unless `--approve-cap` equals `--run-usd`. The reports are written to `runs/incidents/inc-01/record/` (`report.json`, `events.json`, `calls.json`).

### Demo
<!-- FILL: link to the deployed recorded-mode demo and the YouTube video. Recorded mode replays a stored run and costs nothing. -->

## Results

All incidents are synthetic and say so in every file. Six incidents (three dev, three test) with known root causes, each in three configurations: (a) the hierarchy, (b) a single Nemotron-3-Ultra reading the same slices, (c) a single Nemotron-3.5-Lightning reading the same slices. All three use the same slicer, the same operator prompt, the same deterministic evidence check and the same budget rules. The test split is reported apart from dev.

| Configuration | Diagnosis correct (test split) | Real cost | Slices read | First-pass citation validity |
|---|---|---|---|---|
| (a) hierarchy | TBD | TBD | TBD | TBD |
| (b) single Ultra | TBD | TBD | TBD | TBD |
| (c) single Lightning | TBD | TBD | TBD | TBD |

<!-- FILL from benchmarks/results/ only. Do not write any number that is not in a result file. -->

First-pass citation validity is reported twice: as the model wrote it, and after a deterministic rewrite of the citation's source id to the slice it was given. Both numbers are in every report.

## Limitations

- The corpus is synthetic. Good scores on it do not prove accuracy on real incidents.
- `diagnosis_correct` is a category match plus at least one verified essential citation. A model can name the right category for the wrong reason.
- Verified citations prove that evidence exists, not that the diagnosis is right.
- Some runs end inconclusive or read only part of the evidence when the budget runs out. The report says so.
- The auditor is a model and may favor outputs like its own. A deterministic check always runs first.
- Public datasets used in the proof domains may be in the models' training data.
- v1 executes nothing and holds no credentials for any system.

## Proof domains

The same engine runs two other domains by swapping skills and evidence bundles: SOC alert triage (splunk/attack_data, Apache-2.0) and smart-contract review (smartbugs-curated). These are generality checks, not products. <!-- FILL: results, or delete this section if they are not run. -->

## Repository map

- `core/`: ledger, harness (retries, repair, escalation, record and replay), evidence check, slicing, team (director, managers, operators, auditor), API models.
- `config/`: models, prices, rate limits, budget policy, benchmark setup.
- `skills/`: reading skills for the operators.
- `benchmarks/`: synthetic incident corpus and its generator inputs.
- `docs/ARCHITECTURE.md`: design and decisions. `docs/api.md`: the API between core and web. `FEEDBACK.md`: feedback on Token Factory and Nemotron.

## License

MIT. Adapted third-party skills keep their own licenses (see `THIRD_PARTY_NOTICES.md` and `licenses/`).
