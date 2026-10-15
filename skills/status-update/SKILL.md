---
name: status-update
description: Write incident status updates, summaries and stakeholder drafts (placeholder ITOps role) that lead with what changed and keep guesses labeled.
source_url: https://github.com/incident-io/skills/tree/6af50e2e23e9c782b95a456aab5a053550fba3c9/plugins/incident-io/skills/incidents/references
upstream_version_or_commit: incident-io 1.20261014.705 at 6af50e2e23e9c782b95a456aab5a053550fba3c9
license: MIT
copyright_holder: incident.io
adapted_for: nemotron
roles: [status-updater]
modifications: Placeholder until the ITOps and DevOps use case is final. Kept the tool-independent parts of skills/incidents/references/writing.md (update messages, summaries, stakeholder comms, keeping analysis honest); removed drafting and posting through incident.io tools, channel messages, status pages and the AI investigation workflow; added the rule that demo incidents are simulated; added a rule that keeps the required output format.
---
Write incident updates for the incident in the task. Demo incidents are simulated: label every one as simulated.

Readers take updates as a series, each building on the last:

- Lead with what changed since the last update: new findings, clearer impact, mitigations deployed. Do not repeat earlier updates.
- Do not restate structured changes (status, severity, roles, fields); they are recorded on their own.
- State impact specifically: "three EU customers seeing about 2 s payment delays", not "some customers affected". Name the component and the failure mechanism once known.
- Write as "we", in active voice, facts only. No speculation and no filler next steps such as "we'll update when we know more".
- Link the resources you mention when the task gives links.
- For an administrative update, such as pausing for the night, state the fact with a little context and stop.
- When a request holds only structured changes with nothing narrative to add, write no message.

A summary describes the present state, not the history. Reuse an existing summary's section labels; without one, use Problem, Impact, Causes and Steps to resolve. Quantify the impact and state only confirmed causes.

Stakeholder comms are drafts a person sends; never claim one was sent. A customer message leads with impact and what you are doing, in plain language. An executive briefing covers impact, mitigation and ETA, in a few lines.

Keep analysis honest. Your own read of the cause is a hypothesis until a responder states it as fact: never call it confirmed, and label it ("our leading theory", "not proven yet"). Keep the hedging of any findings you relay. Once a responder states the cause, write it as they did.

Keep the output format the task requires (for example JSON).
