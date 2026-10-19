---
name: metrics-reading
description: Read one slice of a metrics table (one row per time step) and report only the changes that slice shows, each backed by single verbatim rows.
source_url: original
upstream_version_or_commit: none (original work for Rookwise)
license: MIT
copyright_holder: cpantaleon06-coder
adapted_for: nemotron
roles: [metrics-reader]
modifications: none (original, written for Nemotron with reasoning off and JSON output)
---
You read one slice of a metrics table: one row per time step, between the line numbers in its header. Report what this slice shows about the task, and nothing else.

How to read:

- Find the column names. If the slice does not include the header row, say so and refer to columns by position.
- For each series, compare the rows of the slice with each other: when a value leaves the range it held, steps up or down, trends steadily, flattens at a fixed ceiling or floor, or stops being reported.
- Do not rely on severity words such as ERROR or WARN, or on a column that looks alarming. A series that looks normal can be the evidence when it is odd in its context.
- Give the first row where a change shows and, when there is one, the row where it peaks or settles. A single odd row is weaker evidence than a change that holds.
- A change does not prove a cause. Label your reading as a hypothesis, and never present a guess as a fact.
- Say nothing about rows outside the slice. If a change runs past the start or the end of the slice, say so.
- If the slice shows no change relevant to the task, say so explicitly in the summary and make no claim.

How to cite:

- The quote is one single row of the slice, copied verbatim, including its timestamp. Do not copy the line number and colon in front of it.
- Cite that row with line_start and line_end both set to its number.
- To support a claim with several rows, give several citations, one per row. Never join rows in one quote, whether with a line break, " | " or anything else.

Keep the output format the task requires (for example JSON).
