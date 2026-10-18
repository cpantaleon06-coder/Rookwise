> SYNTHETIC runbook for Rookwise benchmark incident inc-03, written by scripts/gen_incidents.py (seed 20261017). Fictional: every host, address, key, person and event is made up.

# Runbook: storefront-api 5xx

1. Check storefront_5xx_pct in metrics.csv and which routes fail in storefront-api.
2. Check whether the failing calls wait on cart-svc and how long cart-svc takes.
3. Check recent deploys of storefront-api, including config files (deploy.diff).
4. Roll back if a deploy correlates with the errors.
