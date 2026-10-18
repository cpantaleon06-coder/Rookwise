> SYNTHETIC runbook for Rookwise benchmark incident inc-06, written by scripts/gen_incidents.py (seed 20261017). Fictional: every host, address, key, person and event is made up.

# Runbook: media uploads failing

1. Check upload_fail_rps in metrics.csv and the failures in upload-worker.
2. Check media-api for storage errors and the /data volume usage.
3. Check logrotate activity on the media-api hosts.
4. Check recent deploys, including ops config (deploy.diff).
