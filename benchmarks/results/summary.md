# Benchmark results

Written by scripts/run_benchmark.py from the result files in runs/ (metrics only). The test split is reported apart from the dev split; tuning ends before test runs.

## Dev split

| configuration | runs | incidents | diagnosis_correct_rate | category_correct_rate | evidence_recall_mean | citation_verified_rate_mean | spent_usd_mean | spent_usd_total | partial_runs | commits |
|---|---|---|---|---|---|---|---|---|---|---|
| a | 3 | 3 | 1.0 | 1.0 | 0.5556 | 1.0 | 0.289513 | 0.868538 | 3 | b3aedd4 |
| b | 3 | 3 | 0.3333 | 0.3333 | 0.1111 | 1.0 | 0.409086 | 1.227259 | 3 | b3aedd4 |
| c | 3 | 3 | 0.3333 | 0.3333 | 0.1667 | 0.3333 | 0.120720 | 0.362161 | 3 | b3aedd4 |

## Test split

No runs yet.
