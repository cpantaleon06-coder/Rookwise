> SYNTHETIC ticket for Rookwise benchmark incident inc-05, written by scripts/gen_incidents.py (seed 20261017). Fictional: every host, address, key, person and event is made up.

# Alert: orders-api slow, database errors

Fired at 03:15 UTC: orders-api p95 latency above 4 s for 10 minutes.
orders-api logs "could not get a connection". Is the database down?

Window to investigate: 00:00 to 06:00 UTC on 2026-06-23.
Sources: logs/orders-api.log, logs/pg-proxy.log, logs/notify-worker.jsonl, metrics.csv, deploy.diff, runbook.md.
