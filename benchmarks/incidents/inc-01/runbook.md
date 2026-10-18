> SYNTHETIC runbook for Rookwise benchmark incident inc-01, written by scripts/gen_incidents.py (seed 20261017). Fictional: every host, address, key, person and event is made up.

# Runbook: invoice payments failing

1. Check the edge-proxy 5xx rate for POST /v1/invoices/pay in metrics.csv.
2. Check billing-api for failed calls to the payment gateway and their reason.
3. Check recent deploys of billing-api (deploy.diff).
4. Check the invoice-worker queue for collect-payment failures.
5. Escalate to the payment gateway's support if their side is down.
