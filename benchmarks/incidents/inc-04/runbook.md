> SYNTHETIC runbook for Rookwise benchmark incident inc-04, written by scripts/gen_incidents.py (seed 20261017). Fictional: every host, address, key, person and event is made up.

# Runbook: slow checkout

1. Check checkout_p95_ms and checkout_cpu_pct in metrics.csv.
2. Check recent deploys of checkout-api (deploy.diff) and when they finished.
3. Check how long checkout-api's calls to its dependencies take.
4. Check edge-proxy for 504 on POST /v1/checkout.
5. Roll back only if the timing of a deploy matches the slowdown.
