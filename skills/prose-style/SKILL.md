---
name: prose-style
description: Remove predictable AI writing patterns from prose (filler, formulaic structures, passive voice, vague claims) and rate text against a five-part rubric.
source_url: https://github.com/hardikpandya/stop-slop
upstream_version_or_commit: 8da1f030185bdfe8471220585162991eaeb970e9
license: MIT
copyright_holder: Hardik Pandya
adapted_for: nemotron
roles: [copywriter, researcher, auditor]
modifications: Merged SKILL.md, references/phrases.md and references/structures.md into one short instruction set; dropped the examples file, file links, author metadata and some list entries; added a closing rule that keeps facts, quotes and the required output format unchanged.
---
Write prose without predictable AI patterns.

1. Cut filler. Remove throat-clearing openers ("Here's the thing", "It turns out", "The truth is", "Let me be clear"), emphasis crutches ("Full stop.", "Let that sink in.", "Make no mistake"), meta-commentary ("In this section, we'll", "As we'll see", "Let me walk you through") and filler phrases ("At its core", "It's worth noting", "At the end of the day", "When it comes to").
2. Cut adverbs, softeners and intensifiers: "really", "just", "literally", "genuinely", "honestly", "simply", "actually", "deeply", "truly", "fundamentally", "inherently", "inevitably", "importantly", "crucially".
3. Replace business jargon with plain words: navigate becomes handle, unpack becomes explain, deep dive becomes analysis, moving forward becomes next, circle back becomes revisit, game-changer becomes significant.
4. State the point directly. Drop binary contrasts ("It's not X. It's Y.", "not just X but also Y"), negative listing ("Not a X. Not a Y. A Z.") and rhetorical setups ("What if...?", "Think about it:", "Here's what I mean:").
5. Use active voice with a human subject. Name who acted. Give no human verbs to things: a complaint does not become a fix and a decision does not emerge; a person fixes or decides.
6. Be specific. Replace vague declaratives ("The implications are significant", "The stakes are high") with the specific thing. Drop lazy extremes (every, always, never, nobody) that make sweeping claims.
7. Address the reader as "you" rather than "people". Drop narrator-from-a-distance lines ("Nobody designed this", "This is why...").
8. Vary rhythm. Mix sentence lengths and prefer two items to three. Use no em dashes and no staccato fragments. Vary paragraph endings instead of closing each on a punchy line. Start no sentence with What, When, Where, Which, Who, Why or How, and no paragraph with "So".
9. Trust the reader. State facts, skip softening and hand-holding, and rewrite any line that reads like a pull-quote.

Before returning text, check for adverbs, passive voice, things given human verbs, "not X, it's Y" contrasts, em dashes, three sentences of the same length in a row, and vague declaratives.

To review text, rate it from 1 to 10 on Directness (statements, not announcements), Rhythm (varied, not metronomic), Trust (respects the reader), Authenticity (sounds human) and Density (nothing to cut). A total below 35 of 50 means revise.

Keep facts, numbers, names, quotes and the output format the task requires (for example JSON) unchanged. These rules shape the prose only.
