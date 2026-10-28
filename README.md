# Rookwise

Rookwise investigates operational incidents for small teams that have no dedicated SRE, under a hard budget the user sets before the run. Cheap models read the logs in slices, a strong model judges, deterministic code checks every cited line, an independent auditor reviews the result, and a human decides. In v1 Rookwise only reads and recommends: it executes nothing.

Built for the Nebius x NVIDIA Global AI Hackathon 2026 on NVIDIA Nemotron models served by Nebius Token Factory.

> Every number in the "Results" section comes from the measured run files in `benchmarks/results/runs/`, aggregated by `release/results_json.py`.

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

Tavily: operators have a web search tool for error signatures and advisories (`core/tools/tavily.py`). None of the 18 benchmark runs and neither published recording called it.

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

### The web demo

The site in `web/` is a static app (Vite and React) that replays a recorded real run in the browser. It makes no model calls and no network calls except fetching the recording files. Live runs are not offered. To run it locally: `cd web && npm ci && npm run dev`. Deploy steps for Vercel are in [`web/README.md`](web/README.md).

## Results

All incidents are synthetic and say so in every file. Six incidents with known root causes: three development incidents (inc-01, inc-03, inc-05) used while tuning, and three test incidents (inc-02, inc-04, inc-06) that were not used while tuning. The engine was frozen before the test split ran (see `docs/DECISIONS.md`). Each incident ran once in three configurations, all on the same slicer, the same operator prompt, the same deterministic evidence check and the same hard cap of 0.50 USD:

- (a) the hierarchy,
- (b) a single Nemotron-3-Ultra reading the same slices,
- (c) a single Nemotron-3.5-Lightning reading the same slices.

**Test split (3 incidents per configuration):**

| Configuration | Correct | Evidence recall | Coverage | Real cost per run (USD) |
|---|---|---|---|---|
| (a) hierarchy | 2 of 3 | 0.333 | 0.920 | 0.250 |
| (b) single Ultra | 0 of 3 | 0.222 | 0.107 | 0.386 |
| (c) single Lightning | 1 of 3 | 0.222 | 0.705 | 0.119 |

**Development split (used while tuning):**

| Configuration | Correct | Evidence recall | Coverage | Real cost per run (USD) |
|---|---|---|---|---|
| (a) hierarchy | 3 of 3 | 0.556 | 0.880 | 0.290 |
| (b) single Ultra | 1 of 3 | 0.111 | 0.218 | 0.409 |
| (c) single Lightning | 1 of 3 | 0.167 | 0.706 | 0.121 |

`Correct` means the diagnosis category matches the known category and at least one verified essential citation is present. Coverage is the share of evidence slices that were read. Every number comes from `benchmarks/results/` and can be recomputed with `python release/verify_benchmark.py`.

**Per-run detail, test split:**

| Incident | Config | Category named | Truth | Correct | Claims supported / withdrawn | Slices read | Real cost (USD) |
|---|---|---|---|---|---|---|---|
| inc-02 | a | resource_leak | resource_leak | yes | 3 / 3 | 63 of 65 | 0.246234 |
| inc-02 | b | code_regression | resource_leak | no | 4 / 2 | 7 of 65 | 0.383328 |
| inc-02 | c | resource_leak | resource_leak | yes | 6 / 0 | 40 of 65 | 0.131690 |
| inc-04 | a | code_regression | dependency_latency | no | 4 / 2 | 57 of 72 | 0.316251 |
| inc-04 | b | code_regression | dependency_latency | no | 2 / 2 | 10 of 72 | 0.387522 |
| inc-04 | c | none (inconclusive) | dependency_latency | no | 0 / 0 | 55 of 72 | 0.137689 |
| inc-06 | a | disk_exhaustion | disk_exhaustion | yes | 4 / 2 | 53 of 53 | 0.187499 |
| inc-06 | b | bad_config | disk_exhaustion | no | 1 / 0 | 4 of 53 | 0.385831 |
| inc-06 | c | capacity_exhaustion | disk_exhaustion | no | 6 / 0 | 39 of 53 | 0.086628 |

### What the results do and do not show

- **Three runs per cell is a signal, not statistics.** Two of three against one of three cannot be told apart from chance. The advantage of the hierarchy over the cheapest single model is not proven.
- **Single Ultra loses mainly by reading too little.** With the same cap it read between 4 and 16 slices out of 53 to 73, and the ledger refused 43 to 59 calls per run. This is a comparison at equal money, not a verdict on the model.
- **Verified citations do not prove the diagnosis is right.** On inc-06 the single Lightning run had 6 supported claims and named the wrong category.
- **A near miss.** On inc-04 the hierarchy named code_regression (truth: dependency_latency) and cited lines 2412 and 2413, next to the essential line 2414.
- **Rookwise may say it does not know.** The single Lightning run ended inconclusive on three of the six incidents (inc-03, inc-04, inc-05), with no supported claim, and the result file records it as inconclusive.
- **Cost.** The hierarchy cost about a quarter less than predicted on the test split (0.749984 real against 1.005605 predicted in total).
- **Time.** A hierarchy run usually takes 14 to 17 minutes; one test run took 9186 seconds. We did not find the cause of that outlier.

First-pass citation validity (the share of citations that pass the check on the first reply) averaged 0.893 for the hierarchy on the test split, after a deterministic rewrite of each citation's source id to the slice the model was given. The result files record the number after that rewrite only.

## Limitations

- The corpus is synthetic. Good scores on it do not prove accuracy on real incidents, and no real team has used Rookwise.
- Three incidents per split and one run per cell.
- `Correct` is a category match plus at least one verified essential citation. A model can name the right category for the wrong reason.
- Verified citations prove that evidence exists, not that the diagnosis is right.
- Many runs finish `partial`: not every slice was read or not every operator task finished. The report says so.
- The auditor is a model and may favor outputs like its own. The deterministic check always runs first.
- A root cause can list a claim that the check withdrew; the web app flags that case.
- The public demo replays recorded runs. It does not run on your logs.
- v1 executes nothing and holds no credentials for any system.

## Repository map

- `core/`: ledger, harness (retries, repair, escalation, record and replay), evidence check, slicing, team (director, managers, operators, auditor), API models.
- `config/`: models, prices, rate limits, budget policy, benchmark setup.
- `skills/`: reading skills for the operators.
- `benchmarks/`: synthetic incident corpus, ground truth and the benchmark results.
- `web/`: the static replay site. `examples/api/recordings/`: the recorded runs it plays.
- `release/`: scripts that check the benchmark numbers, the README numbers and the submission requirements.
- `docs/ARCHITECTURE.md`: design. `docs/DECISIONS.md`: decisions, the engine freeze and the post-freeze changes. `docs/api.md`: the API between core and web.
- `FEEDBACK.md`: feedback on Token Factory and Nemotron, entry by entry, with the calls that show each finding.

## Updates during the submission period

The submission period runs from 2026-08-26 to 2026-10-30. This repository's first commit is dated 2026-10-12, so Rookwise was built inside the period. Adapted third-party skills and their licenses are listed in `THIRD_PARTY_NOTICES.md`.

## License

MIT. Adapted third-party skills keep their own licenses (see `THIRD_PARTY_NOTICES.md` and `licenses/`).
