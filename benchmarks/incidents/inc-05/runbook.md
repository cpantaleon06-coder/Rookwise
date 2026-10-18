> SYNTHETIC runbook for Rookwise benchmark incident inc-05, written by scripts/gen_incidents.py (seed 20261017). Fictional: every host, address, key, person and event is made up.

# Runbook: orders-api slow or failing

1. Check orders_p95_ms and orders_rps in metrics.csv.
2. Check orders-api for database connection errors.
3. Check pg-proxy for its connection counts and the database for load.
4. Check recent deploys (deploy.diff) and autoscaler activity.
5. Escalate to the database owner if the database is unhealthy.
