#!/usr/bin/env bash
# Score every incident with Laya (tools/laya-filter/score.mjs): all chunks that hold an evidence or
# decoy line, plus 120 seeded random other chunks (see PROTOCOL.md, "Deviation"). About 20 minutes
# per incident on the machine in REPORT.md. Run from the repo root after `node tools/laya-filter/download.mjs`.
set -euo pipefail
out=benchmarks/log_filter/results/laya
mkdir -p "$out"
for id in "$@"; do
  dir=benchmarks/log_filter/corpus/$id
  log=$(ls "$dir"/"$id".synthetic.*)
  node tools/laya-filter/score.mjs "$log" "$out/$id.json" --truth "$dir/truth.json" --sample 120 --seed 20261017
done
