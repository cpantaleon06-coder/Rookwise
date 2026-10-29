# Design direction

The web app reads like a careful technical report with live figures: a single reading column,
numbered sections, numbered figures and tables with source lines, hairline rules and whitespace.
Earlier directions (a rounded, glowing landing and a colorful pass) are superseded; their notes
were removed from this file and live in the git history.

## 1. Principles

- **One reading column.** The landing is one column of 68 characters (62 to 72 at the body size),
  centered, with generous margins. Tables and figures stay inside it.
- **Numbered structure.** Abstract, then 1 Problem, 2 Method, 3 Results, 4 Limitations,
  5 Reproduce, then the demo link.
- **Every figure and table has a caption and a source line** that names the file it was built
  from: a recording in `web/public/recordings/` or the run files in `benchmarks/results/runs/`.
- **No decoration.** No cards, drop shadows, pill buttons, large rounded boxes, gradient washes,
  glows or mascots. Hairline rules, whitespace, small caps labels. Border radius 2 to 4 px.
- **Tables in booktabs style:** a top rule, a thin rule under the header, a bottom rule, no
  vertical lines; lining, tabular figures.
- **Buttons** are flat rectangles (primary) or underlined text actions (secondary), with a focus
  ring of a solid outline plus an accent halo.
- **Symmetry and spacing:** a central vertical axis for the header, title blocks and actions;
  margin, padding and gap only on the Fibonacci scale 8, 13, 21, 34, 55, 89, 144 px.
- **Trust signals, from data only:** the run view shows a provenance line (run id, recorded date,
  the commit the run was recorded at, the models, "Synthetic incident"), keeps "Recorded run, not
  live" and "Executes nothing" visible, and shows each withdrawn claim with its exact reason code
  and the failing log line. Nothing is invented: a field the recording lacks is left out.

## 2. Color

Two themes over the same anchors: **paper** (ink on bone) for the landing and **ink** (bone on ink)
for the run view. Ink `#142030`, bone `#EAE4D3` and Stellar Strawberry `#FF5C8D` are the anchors.
Strawberry is used sparingly: link underlines, the withdrawn mark, the decision accent.

Muted semantic marks appear only where they carry a meaning, and always next to a word and a
symbol:

| Meaning | Symbol | Paper | Ink |
|---|---|---|---|
| Supported (claim verified) | ✓ | `#1A5E3E` deep green | `#7CCFA3` |
| Withdrawn (claim removed by the check) | ✕, strikethrough, footnote | `#A3204F` deep strawberry | `#FF5C8D` Strawberry |
| Auditor (second check) | ◇ | `#3B3F8F` indigo | `#AEB2F0` |
| Cost (money) | $ | `#6E4A0C` ochre | `#D9AA52` |

Strawberry itself is 2.31:1 on bone, too light for text, so on paper the withdrawn mark uses a deep
shade of it. Tints are the mark at 10% over bone (paper) or 14% over ink (ink).

### Contrast (WCAG 2.x, computed)

| Pair | Paper | Ink |
|---|---|---|
| Body text on background | 12.93:1 | 12.93:1 |
| Muted text on background | 5.77:1 | 7.29:1 |
| Primary button text on its fill | 12.93:1 | 12.93:1 |
| Strong rule on background (non-text, 3:1) | 3.51:1 | 3.19:1 |
| Supported on background / on its tint | 6.09 / 5.29 | 8.84 / 6.54 |
| Withdrawn on background / on its tint | 5.75 / 4.90 | 5.60 / 4.71 |
| Auditor on background / on its tint | 7.21 / 6.21 | 8.15 / 6.16 |
| Cost on background / on its tint | 6.25 / 5.43 | 7.68 / 5.95 |
| Body text on any mark tint (lowest) | 11.03:1 | 9.55:1 |
| Muted text on any mark tint (lowest) | 4.92:1 | 5.39:1 |

Every text pair clears 4.5:1.

## 3. Type

All SIL Open Font License 1.1, self-hosted through Fontsource npm packages, latin subset only.

- **Source Serif 4** (variable): headings and long prose. Body 18 px, line height 1.618.
- **Nunito** (variable): labels, buttons, chips, captions and notes.
- **IBM Plex Mono** 400: log lines, citations, line numbers and money.

Sizes follow the golden scale 18, 29, 47, 76, 123 px (`web/src/lib/scale.ts`, checked by
`scale.test.ts`). Tables use lining, tabular figures.

## 4. Motion

150 to 300 ms, ease-out, no bounce, no parallax. Reduced motion renders the final state.

- Replay steps reveal in sequence: each new feed row fades in with a 6 px rise (220 ms).
- A verified citation's line gets its supported background through a 300 ms fade.
- A withdrawn claim's strikethrough is drawn left to right once (300 ms).
- The budget bar's width eases (300 ms) as spend accumulates in the replay.
- Hold to approve keeps its 1.618 s hold with a progress ring, plus Space or Enter held down, and a
  two-step Approve then Confirm path announced to screen readers; with reduced motion only the two
  steps are offered.

## 5. The run view

A document, not a dashboard of cards: a recorded-run line, the title and goal, the provenance
line, a ruled status line (team, budget, status), the replay controls, then a main column
(diagnosis and evidence, the approval gate, the delivery package, the steps, the tasks) and a
margin column of notes (safeguards that fired, audit, coverage, budget ledger, team, chat).

The team line shows only what the recording holds. Operators get a final state from their task
results (for inc-03-run2: 60 done, 7 failed, 7 escalations). The recording keeps no final state for
the director, managers or auditor (their org entries stay at "hired"), so for them the line shows
the count and the model only.

## 6. Deviations

- **Dev rows in Table 2:** the brief asks for the test split first, then dev. The dev numbers come
  from the same run files (`release/out/results.json`) and were not on the site before.
- **Narrow screens:** Table 2 keeps its five columns and scrolls sideways inside a labeled,
  focusable region, with a visible hint; the page itself never scrolls sideways.
- **Footnotes:** a withdrawn claim's failing line stays in the claim's cited lines; the footnote
  gives the reason code and points at that line instead of repeating it.
- **The dot-matrix rook, rings, glyphs, ticker and washes** of earlier passes are removed, with the
  three tests of the dot-matrix sampler.

## 7. Middle pass (structure from the report, surface from the references)

Structure, tables and prose stay as above. The surface takes from the references: pill buttons
and pill status chips (verified, withdrawn, auditor, cost, each with a symbol and a word), a soft
Strawberry glow behind the dot-matrix rook in the hero, gentle washes behind the hero (soft-edged,
drifting over 24 s, static with reduced motion) and behind the results figure, coverage rings
(Figure 2), and 21 to 34 px radii on figures. Boxed elements: the results figure on the landing and
the approval gate on the run view, one per screen.

Contrast added by this pass (computed against the brightest pixel):

| Pair | Ratio |
|---|---|
| Paper primary pill: bone on deep Strawberry | 5.75:1 |
| Ink primary pill and "Decision needed": ink on Strawberry | 5.60:1 |
| Paper wash peaks (Strawberry 12%, indigo 10%): body text | 11.63 / 11.13 |
| Paper wash peaks: muted text | 5.19 / 4.97 |
| Ink wash peaks: body / muted text | 11.18 and 10.61 / 6.30 and 5.98 |
| Ink wash peaks: Strawberry text | 4.60 / 4.85 |
| "Recorded run, not live" pill, paper / ink | 6.21 / 6.16 |

Weak spots left: the run view's provenance line wraps awkwardly at 390 px; long JSON log lines wrap
heavily on phones; table configuration names wrap inside the results box at 1280 px.
