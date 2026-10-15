---
name: deploy-checklist
description: Produce a pre-deployment checklist with pre-deploy, deploy and post-deploy steps and rollback triggers.
source_url: https://github.com/anthropics/knowledge-work-plugins/tree/f652327d4e953d7957d99e735c3c7f9964e9d2e5/engineering/skills/deploy-checklist
upstream_version_or_commit: engineering 1.2.0 at f652327d4e953d7957d99e735c3c7f9964e9d2e5
license: Apache-2.0
copyright_holder: Anthropic (plugin author; the LICENSE file has no copyright line)
adapted_for: nemotron
roles: [deploy-reviewer]
modifications: This file was modified from the original. Removed the slash command, usage block, connector sections, tips, the date and deployer header and the claim to remember a deploy process; turned the markdown template and customization notes into instructions; added a rule that keeps the required output format.
---
Produce a pre-deployment checklist for the release in the task.

- Pre-deploy: all tests passing in CI; code reviewed and approved; no known critical bugs in the release; database migrations tested (if applicable); feature flags configured (if applicable); rollback plan documented; on-call team notified.
- Deploy: deploy to staging and verify; run smoke tests; deploy to production (canary if available); monitor error rates and latency for 15 minutes; verify key user flows.
- Post-deploy: confirm metrics are nominal; update release notes or the changelog; notify stakeholders; close related tickets.
- Rollback triggers, decided before the deploy and not during it: error rate above X%, P50 latency above X ms, a critical user flow failing. Use the thresholds the task gives and keep X where it gives none.

Adapt the checklist to the release: feature flags add flag verification steps, a database migration adds migration-specific checks, and a breaking API change adds consumer notification steps.

Keep the output format the task requires (for example JSON).
