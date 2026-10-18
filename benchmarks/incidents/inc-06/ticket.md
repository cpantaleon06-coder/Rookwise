> SYNTHETIC ticket for Rookwise benchmark incident inc-06, written by scripts/gen_incidents.py (seed 20261017). Fictional: every host, address, key, person and event is made up.

# Alert: media uploads failing

Fired at 04:52 UTC: upload failure rate above 50% for 10 minutes.
upload-worker reports store failures; media-api answers 507 on POST /v1/uploads.

Window to investigate: 00:00 to 06:00 UTC on 2026-07-15.
Sources: logs/media-api.log, logs/upload-worker.jsonl, metrics.csv, deploy.diff, runbook.md.
