# Stage-0 log filter experiment: report

Date: 2026-10-17. Time box: one day. Protocol: `PROTOCOL.md`, written before any filter was
scored on the test incidents (one dated deviation, below). All data is SYNTHETIC. No model API
was called; Laya ran locally on CPU.

## Verdict

**Laya fails, so drop it.** It kept every test evidence line, but only because the threshold
had to sit so low that it also kept almost everything else. On the test incidents it removed
14.3% of tokens (95% interval 9.7% to 21.0%) with the `noul` question, and 5.6% with the
two-option `choice` question. The keyword filter removed 92.6%. Laya also takes about 5 to 10
seconds per chunk of 2 to 5 new log lines on this laptop: 1.5 to 6 hours per incident, against
under a second for the keyword filter.

| Pre-registered criterion (test incidents, pooled) | C: `noul` | C2: two-option `choice` |
|---|---|---|
| Recall of planted evidence >= 95% | 100% (16/16): pass | 100% (16/16): pass |
| Tokens removed >= 50% | 14.3% (9.7% to 21.0%): **fail** | 5.6% (2.9% to 10.9%): **fail** |
| Better than filter B at equal recall | **fail**: recall is higher than B's (100% vs 75%), but it removes 14.3% of tokens against B's 92.6% | **fail**: 5.6% against 92.6% |

Two question forms were tried, which gave Laya a second chance; neither passes.

## Results

Tokens use the repo's input estimate, `config/harness.json` `input_estimate`: characters / 3
(the per-message 64-token margin is the same with or without a filter and is left out). The text
counted is what an operator would read: each kept line as `N: line` with its original number, one
marker per run of dropped lines. `~` marks values estimated from a sample (see "Deviation").

Test incidents (thresholds frozen from dev: C 0.5088, C2 0.5367):

| Filter | Evidence kept (recall) | Tokens before | Tokens after | Tokens removed | Decoys kept |
|---|---|---|---|---|---|
| A: no filter | 16/16 (100.0%) | 1,458,260 | 1,458,260 | 0.0% | 7/7 |
| B: keyword/regex | 12/16 (75.0%) | 1,458,260 | 107,544 | 92.6% | 7/7 |
| C: Laya `noul` | 16/16 (100.0%) | 1,458,260 | ~1,250,196 | 14.3% (9.7% to 21.0%) | 7/7 |
| C2: Laya `choice` | 16/16 (100.0%) | 1,458,260 | ~1,376,955 | 5.6% (2.9% to 10.9%) | 7/7 |
| D: B or C | 16/16 (100.0%) | 1,458,260 | ~1,262,350 | 13.4% (9.1% to 19.8%) | 7/7 |
| D2: B or C2 | 16/16 (100.0%) | 1,458,260 | ~1,381,732 | 5.2% (2.8% to 10.3%) | 7/7 |

Dev incidents (where B was designed and the thresholds were picked, so overfitting shows here):

| Filter | Evidence kept (recall) | Tokens before | Tokens after | Tokens removed | Decoys kept |
|---|---|---|---|---|---|
| A: no filter | 17/17 (100.0%) | 1,116,709 | 1,116,709 | 0.0% | 7/7 |
| B: keyword/regex | 17/17 (100.0%) | 1,116,709 | 96,573 | 91.4% | 7/7 |
| C: Laya `noul` | 17/17 (100.0%) | 1,116,709 | ~1,020,123 | 8.6% (5.6% to 14.2%) | 7/7 |
| C2: Laya `choice` | 17/17 (100.0%) | 1,116,709 | ~1,106,732 | 0.9% (0.3% to 4.5%) | 7/7 |
| D: B or C | 17/17 (100.0%) | 1,116,709 | ~1,026,733 | 8.1% (5.2% to 13.3%) | 7/7 |
| D2: B or C2 | 17/17 (100.0%) | 1,116,709 | ~1,107,412 | 0.8% (0.2% to 4.2%) | 7/7 |

Per test incident:

| Filter | Incident | Evidence kept | Tokens removed | Decoys kept | Evidence missed (line) |
|---|---|---|---|---|---|
| B | test-1 | 3/5 | 92.2% | 3/3 | 4085, 4560: DNS lookups that took 5 s but succeeded |
| B | test-2 | 4/5 | 91.9% | 2/2 | 3150: the autoscaler doubling the pool |
| B | test-3 | 5/6 | 93.9% | 2/2 | 1800: log volume jumping to 4,800 lines/s (routine: 90 to 180) |
| C | test-1 | 5/5 | 17.5% (11.7% to 25.2%) | 3/3 | none |
| C | test-2 | 5/5 | 0.0% (0.0% to 3.1%) | 2/2 | none |
| C | test-3 | 6/6 | 19.9% (13.8% to 27.8%) | 2/2 | none |
| C2 | test-1 | 5/5 | 7.5% (4.0% to 13.6%) | 3/3 | none |
| C2 | test-2 | 5/5 | 0.0% (0.0% to 3.1%) | 2/2 | none |
| C2 | test-3 | 6/6 | 6.6% (3.4% to 12.5%) | 2/2 | none |

Every filter kept every decoy error: none of them tells a decoy from evidence.

### Why Laya fails here

Its scores barely separate routine chunks from evidence chunks. Over the 720 sampled routine
chunks, P(true) for the `noul` question had a median of 0.74 (10th percentile 0.52, 90th 0.88).
The lowest-scoring evidence chunks scored 0.51 (dev-2, a slow but successful request) and 0.51
(test-3, an outright `ERROR ... status 500` checkout failure). A threshold that keeps all the
evidence therefore keeps most routine chunks too. The post-hoc sweep on test shows there is no
good operating point: at threshold 0.6, `noul` keeps 81% of the evidence and removes 32% of
tokens; at 0.7, 44% and 61%. Filter B is at 75% recall and 92.6% removed.

### Laya cost on this machine

Machine: Intel Core i3-8130U (2 cores, 4 threads, 2.2 GHz), 15.9 GB RAM, Windows 11 Pro
(10.0.26200), Node 22.21.0, onnxruntime-node 1.30.0 on the CPU execution provider, default
threads (4 threads measured no faster). The CPU was throttled to 1.5 GHz for part of the run
(observed during test-1), so per-chunk times vary.

| Measure | Value |
|---|---|
| First-run download | 1,692,649,422 bytes (1.69 GB) of ONNX weights and tokenizer in 713 s, plus 290 MB of `node_modules` |
| Cold start (`Laya.load`, weights on disk) | 2.9 to 3.1 s when the weights were in the OS file cache; 15.5 to 17.4 s when they were not |
| Peak memory (process RSS) | 2.01 to 2.05 GB with both questions; 1.77 GB with one |
| Per chunk, one question (20 chunks of test-2, CPU at 2.2 GHz) | median 5.1 s (4.4 to 5.9 s) |
| Per chunk, both questions in one pass | 9.4 to 9.9 s on four incidents; 15.9 s (dev-3) and 27.8 s (test-1), the CPU seen at 1.5 GHz during test-1 |
| Chunk size | 457 state tokens after the 55-token question header; about 5 new lines per chunk for plain text, 2 to 2.5 for JSON lines (2-line overlap) |
| Time per incident, one question (projected: chunks x 5.1 s) | 1.5 h (dev-3, 1,028 chunks) to 6.2 h (test-1, 4,400 chunks) |
| Time per incident, keyword filter B (measured, whole log, Python) | 0.2 to 0.6 s |

## Model card: license and intended use

- License: both model cards carry `license: apache-2.0`. The ONNX export card
  (`receptron/laya-onnx`) says the weights are Convai Innovations' and stay under Apache 2.0; the
  export code and `@receptron/laya` are MIT. Notice added to `THIRD_PARTY_NOTICES.md`.
- Intended use (`convaiinnovations/laya`): a non-generative decision model that answers typed
  questions (choice, score, yes/no) about a short state in one forward pass. Its tags are
  classification, routing, scoring, guardrails and moderation. The English root checkpoint has a
  512-token context and is listed as best at English text, guardrails and email triage. Log
  filtering is not mentioned; the closest uses are the fine-tuned checkpoint's "security
  incidents" and "agent-trace observability" workflows. Its "Honest Limits" section warns that the base checkpoints are near chance
  zero-shot on its own typed-decisions benchmark ("Laya is a fast base to specialise, not a
  zero-shot decision engine."). It also warns that on the English checkpoint `noul` answers can
  follow the option labels instead of the input (hence form C2), that the model ships
  over-confident and needs temperature refitting on your own data, and that fine-tuning is where
  accuracy comes from.

## Deviation from the protocol

Scoring every chunk would have taken about 29 hours (about 10,000 chunks at about 10 s), so
before any test scoring the protocol was amended (`PROTOCOL.md`, "Deviation"). Per incident,
every chunk that holds an evidence or decoy line was scored, plus 120 seeded random other
chunks. Recall, decoy survival and the dev thresholds are exact. Tokens removed for C, C2, D and
D2 is an estimate from the sample, with a 95% Wilson interval; B is exact.

## What this does not show (not verified)

- **Real logs.** Everything is synthetic. The same author wrote the incidents, the keyword rules
  and the Laya question, so "B designed from dev only" was a procedure, not a blind test. B's
  dev-to-test drop (100% to 75% recall) is the honest part of that: its rules missed quiet
  evidence they were not written for.
- **Other hardware.** One laptop CPU, partly throttled. No GPU, no other execution provider, no
  quantized (int8) model. The model card reports about 33 ms per request on a T4 GPU and 193 to
  464 ms on a CPU it does not name; the npm README reports about 140 ms per three-question call
  on Apple silicon. Here one question on one 512-token chunk took about 5 s.
- **A true cold start** after a reboot; only warm and evicted file-cache loads were seen.
- **Full scoring.** C and C2 token removal is sampled, not measured on every chunk.
- **Other Laya setups.** Not tried: the multilingual checkpoint (1,024 to 8,192 tokens), the
  typed-decisions checkpoint, fine-tuning, temperature refitting, other question wordings,
  smaller overlap, or scoring lines instead of chunks. Fine-tuning on our own labels might change
  the result, but it costs far more than a day and does not fix the speed.
- **The token rule.** characters / 3 is the repo's estimate, not a tokenizer count. The team
  smoke run found it under-counts log-heavy prompts by about 10%; that affects all filters alike,
  so the shares removed should hold, but absolute token counts are estimates.
- **Downstream quality.** No Nemotron call was made, so whether a filtered log changes the
  operators' answers is not measured.
- **Package maturity.** `@receptron/laya` 0.2.0 was published on 2026-10-16, one day before
  this test.

## A side finding

Filter B is not good enough either: 75% test recall, below the 95% bar. Its misses are the quiet
signals (slow but successful calls, metric jumps, autoscaling) that a keyword filter is blind
to. That is a real reason to want a smarter stage 0, but Laya, used zero-shot, is not it.

## Reproduce

```sh
python benchmarks/log_filter/gen_corpus.py           # corpus; --check compares with manifest.json
cd tools/laya-filter && npm ci && node download.mjs && cd ../..
bash benchmarks/log_filter/run_laya.sh dev-1 dev-2 dev-3 test-1 test-2 test-3   # about 2.5 h here
python benchmarks/log_filter/evaluate.py             # tables, results/summary.json
```

Files: `results/laya/<id>.json` (chunk scores), `results/summary.json` (every number above, the
sweeps and the evidence scores), `results/timing_single_test-2.json` (one-question timing),
`results/download.json`.
