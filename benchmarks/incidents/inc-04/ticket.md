> SYNTHETIC ticket for Rookwise benchmark incident inc-04, written by scripts/gen_incidents.py (seed 20261017). Fictional: every host, address, key, person and event is made up.

# Alert: slow checkout

Fired at 03:18 UTC by edge-proxy: p95 latency on POST /v1/checkout above 3 s; some checkouts time out (504).
A checkout-api deploy went out at 02:40 UTC.

Window to investigate: 00:00 to 06:00 UTC on 2026-07-02.
Sources: logs/checkout-api.log, logs/edge-proxy.log, logs/fraud-worker.jsonl, metrics.csv, deploy.diff, runbook.md.
