> SYNTHETIC runbook for Rookwise benchmark incident inc-02, written by scripts/gen_incidents.py (seed 20261017). Fictional: every host, address, key, person and event is made up.

# Runbook: catalog-api restarts or slow responses

1. Check catalog_restarts_total and catalog_rss_mb in metrics.csv.
2. Check catalog-api for supervisor restarts and their exit codes.
3. Check recent deploys of catalog-api (deploy.diff), including dependency changes.
4. Check edge-proxy for 5xx on /v2/catalog during restarts.
5. Roll back if a deploy correlates with the problem.
