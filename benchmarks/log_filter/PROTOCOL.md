# Stage-0 log filter experiment: protocol

Written on 2026-10-17 before any filter was run on the test incidents. Time box: one day.

Question: is `@receptron/laya` worth using as a cheap local "stage 0" filter that drops log
lines before the Nemotron operators read them?

Everything here is SYNTHETIC: a fictional web service, generated logs, planted evidence.
No model API is called. Laya runs locally on CPU.

## Data

`gen_corpus.py` (seed 20261017) writes six incidents of the fictional service
`harborline-web` into `corpus/`: three `dev-*` and three `test-*`, 5,000 to 20,000 lines each,
plain text and JSON lines. Each has 3 to 8 planted evidence lines, 2 or 3 decoy errors, and a
`truth.json` with the 1-based evidence and decoy line numbers and the root cause. In `dev-2` and
`test-2` no evidence line contains ERROR, WARN or FATAL.

The generated logs are not committed (several MB); `manifest.json` holds their SHA-256 so a
regenerated corpus can be checked byte for byte.

## Filters

All filters return a set of original 1-based line numbers. The filtered text keeps each kept
line as `N: line` (the same form `core/team/auditor.render_source` uses) and replaces each run
of dropped lines with one marker line, so citations keep working with `core/evidence.py`.

- A: no filter.
- B: keyword/regex filter, designed once by reading the dev incidents only, then frozen
  (`filter_keyword.py`).
- C: Laya. The log is split into chunks of whole lines that fit the model's 512-token window
  after the question header (counted with the model's own tokenizer), with a 2-line overlap.
  Each chunk gets one `noul` question; a chunk is kept when P(true) >= threshold.
- C2: same chunks, the same question asked as a two-option `choice` (the model card's own
  workaround for `noul` answers that follow the labels instead of the input). Scored, tuned
  and reported exactly like C. Both are reported; neither is picked after seeing test numbers.
- D: B or C (union of kept lines), with C at its frozen threshold.

## Threshold rule (fixed now)

For C and C2: the threshold is the highest value at which recall on the dev incidents is 100%
(every dev evidence line inside a kept chunk). It is then frozen and applied to the test
incidents once.

## Metrics, reported per incident and pooled, dev and test separately

- Recall: kept evidence lines over all evidence lines.
- Tokens removed: 1 - tokens(filtered text) / tokens(unfiltered text), with tokens estimated by
  the repo rule in `config/harness.json` `input_estimate`: characters / 3. The 64-token margin
  is per message, the same with or without a filter, and is left out.
- Decoy errors that survive.
- Laya cost on this machine: ms per chunk, total seconds per incident, cold start (load with
  the weights on disk), first-run download size, peak memory (RSS) of the Node process.

## Pass criteria (all three on the test incidents, pooled)

1. Recall of C >= 95%.
2. Tokens removed by C >= 50%.
3. C better than B at equal recall: if C's recall >= B's recall, C must remove more tokens than
   B. If C's recall is below B's, C fails this criterion. (A threshold sweep on test is also
   shown, labeled post hoc, only to explain the result; it does not change the verdict.)

## Deviation (2026-10-17, written before any test incident was scored)

A probe on the first 20 chunks of dev-1 measured about 9.8 s per chunk with both question forms
in one forward pass, and about 5.6 s per form asked alone (4 threads instead of the default did
not help). A chunk holds about 6 log lines, so the corpus has roughly 10,000 chunks: scoring
all of them would take about 29 hours, which breaks the one-day time box. Changes:

- Per incident, every chunk that contains an evidence or decoy line is scored (the scorer reads
  `truth.json` only to choose which chunks to score; Laya never sees the labels), plus a seeded
  random sample of 120 other chunks.
- Recall and decoy survival stay exact: they depend only on the chunks that hold those lines.
  The threshold rule depends only on the dev evidence chunks, so it is also exact.
- Tokens removed by C and C2 is estimated: the kept share of the non-labeled lines is taken from
  the sample, with a 95% Wilson interval, and gap markers are ignored for C and C2. B is still
  measured on every line.
- Time per incident for C and C2 is projected: measured ms per chunk times the incident's total
  chunk count.

C2 is judged by the same three criteria and reported next to C. Laya passes if C or C2 passes
all three (two question forms is a second chance for Laya, and the report says so). If neither
passes, the recommendation is to drop it.
