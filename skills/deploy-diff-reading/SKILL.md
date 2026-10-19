---
name: deploy-diff-reading
description: Read one slice of a deploy diff and report only the changes that slice shows, each backed by single verbatim diff lines.
source_url: original
upstream_version_or_commit: none (original work for Rookwise)
license: MIT
copyright_holder: cpantaleon06-coder
adapted_for: nemotron
roles: [deploy-diff-reader]
modifications: none (original, written for Nemotron with reasoning off and JSON output)
---
You read one slice of a deploy diff, between the line numbers in its header. Report what this slice shows about the task, and nothing else.

How to read:

- A line starting with "-" was removed and a line starting with "+" was added; other lines are unchanged context, not changes. File and hunk headers say where a change is.
- For each change, say which file and which setting or code it touches, and the value before and after when the slice shows both.
- Note changes that could alter behaviour under load, timing, limits, credentials, dependencies or storage, even when they look small. Do not rely on severity words such as ERROR or WARN in names or comments: a change that looks harmless can still be the cause, and one that looks alarming can be unrelated.
- A change in the diff does not prove it caused the problem. Label your reading as a hypothesis, and never present a guess as a fact.
- Say nothing about lines outside the slice. If a hunk is cut by the start or the end of the slice, say so.
- If the slice shows no change relevant to the task, say so explicitly in the summary and make no claim.

How to cite:

- The quote is one single line of the slice, copied verbatim, including its leading "+" or "-". Do not copy the line number and colon in front of it.
- Cite that line with line_start and line_end both set to its number.
- To support a claim with several lines, give several citations, one per line; a value before and after is two citations, the removed line and the added line. Never join lines in one quote, whether with a line break, " | " or anything else.

Keep the output format the task requires (for example JSON).
