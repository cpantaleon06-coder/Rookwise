> SYNTHETIC ticket for Rookwise benchmark incident inc-01, written by scripts/gen_incidents.py (seed 20261017). Fictional: every host, address, key, person and event is made up.

# Alert: invoice payments failing

Fired at 03:52 UTC by edge-proxy: 5xx rate on POST /v1/invoices/pay above 5% for 10 minutes.
Support reports customers see "Payment could not be completed" when paying invoices, since about 03:45 UTC.

Window to investigate: 00:00 to 06:00 UTC on 2026-05-04.
Sources: logs/edge-proxy.log, logs/billing-api.log, logs/invoice-worker.jsonl, metrics.csv, deploy.diff, runbook.md.
