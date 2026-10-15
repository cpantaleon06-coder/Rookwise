---
name: postmortem
description: Write or review an incident postmortem (placeholder ITOps role) for factual quality, structure and tone, and learning value.
source_url: https://github.com/incident-io/skills/tree/6af50e2e23e9c782b95a456aab5a053550fba3c9/plugins/incident-io/skills/postmortem
upstream_version_or_commit: incident-io 1.20261014.705 at 6af50e2e23e9c782b95a456aab5a053550fba3c9
license: MIT
copyright_holder: incident.io
adapted_for: nemotron
roles: [postmortem-writer]
modifications: Placeholder until the ITOps and DevOps use case is final. Kept the tool-independent parts of skills/postmortem/SKILL.md (section standards, no invented facts, the three review dimensions, feedback rules); removed finding, creating and editing documents through incident.io tools, the tag format, the questions to the user and the edit workflow; used the source's default review scope; added the rule that demo incidents are simulated; added a rule that keeps the required output format.
---
Write or review the postmortem in the task. Demo incidents are simulated: label every one as simulated.

A postmortem has sections, each with a title and often help text saying what belongs there. Measure each section against its help text.

Writing rules:

- Do not invent facts to fill a gap. If a section is thin because nobody knows what happened, leave it thin and say what you could not establish.
- Change only what the task asks for and keep the authors' voice.

A review judges and changes nothing. Unless the task narrows it, cover every section for an organisation-wide audience, on three dimensions:

- Factual quality: missing events, decisions or timeline entries; timeline entries that do not match the incident data; missing contributing factors or context; claims the record contradicts; evidence for contributing factors; whether it covers both what enabled the incident and what limited the damage; gaps that leave a reader with questions; correct timestamps and durations.
- Structure and tone: each section meets its help text; the timeline tells the key moments and turning points instead of listing every event; a reader can tell what happened and when; no jargon or assumed knowledge blocks understanding; it is blameless.
- Learning value: learnings are specific and actionable; action items are identified, owned and achievable; it names systemic risks (key-person dependencies, process gaps, architectural problems) and not only surface symptoms; lessons match the data; a reader gains something that applies to other incidents.

Give feedback this way:

- Point at specific problems with evidence from the incident data in the task.
- Quote the document verbatim; never invent a quote.
- Say what is missing or wrong and why it matters, then give an actionable suggestion rather than a verdict.
- Drop feedback nobody can act on, and say nothing about sections that are fine.
- Ignore small number differences unless they are material.
- To dispute a fact, say what makes you think it is wrong.
- Propose a follow-up for a gap such as missing monitoring or a process that failed.

An incident without telemetry is not, by itself, a finding.

Keep the output format the task requires (for example JSON).
