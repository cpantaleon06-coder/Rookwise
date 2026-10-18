> SYNTHETIC ticket for Rookwise benchmark incident inc-02, written by scripts/gen_incidents.py (seed 20261017). Fictional: every host, address, key, person and event is made up.

# Alert: catalog-api restarting

Fired at 03:22 UTC: catalog-api restarted 3 times in 20 minutes.
edge-proxy shows short bursts of 503 on /v2/catalog.

Window to investigate: 00:00 to 06:00 UTC on 2026-06-09.
Sources: logs/catalog-api.log, logs/search-indexer.jsonl, logs/edge-proxy.log, metrics.csv, deploy.diff, runbook.md.
