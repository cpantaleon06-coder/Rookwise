# Design direction

This file records what the web redesign took from the reference images, the palette with its
contrast ratios, the shape language, the golden-ratio rules, the screenshot self-review and every
place the build departs from the brief.

## 1. References

The images live in `design-refs/` at the repository root (gitignored, not shipped). No other
reference folder exists.

| File | Bytes |
|---|---|
| AI Landing Page Design.jpg | 77746 |
| Corporate Landing Pages_ 1097 Examples & Inspiration _ Lapa Ninja.jpg | 121655 |
| Daniella.jpg | 45988 |
| Modern Presentation Design _ Graphic Design & Data Visualization.jpg | 53195 |
| Zenixa – UI_UX Case Study for Creative Agency.jpg | 61470 |
| download (2).jpg | 48176 |
| download (3).jpg | 29931 |
| download (4).jpg | 38571 |
| download (5).jpg | 84667 |

### Visual devices and where Rookwise adopts them

The first version of this file listed gradients, glows, dotted art and tickers under "not
taken". Those are the devices that make the references work, so the redesign now uses them,
built only from the three hues. No single reference's composition, text, logo or asset is
reproduced; the site combines their vocabulary into one design of its own.

| Reference | Devices it uses | Where Rookwise adopts the device |
|---|---|---|
| AI Landing Page Design.jpg | Pill badge over a centered headline; filled pill button beside an outline pill; luminous wave lines behind the hero; logo strip; dark cards with 20 px radii, 1 px light borders and a top-lit gradient; a 2x2 bento | Hero buttons as pills (Strawberry fill plus outline); two mirrored glowing arcs behind the hero object; every card uses the top-lit ink gradient and a 1 px bone border. Logo strip not adopted: no third-party logos, so "NVIDIA Nemotron" and "Nebius Token Factory" stay plain text in the footer |
| Lapa Ninja (corporate landing) | One hue on a plain field; engraving illustration framing a centered serif headline; a ticker band of news under the hero; a large statement paragraph | The ticker band under the hero, filled with real facts of the loaded run; the large centered statement of "Why it exists"; one-hue discipline (here three hues). Engraving art not adopted: it is a raster illustration style |
| Daniella.jpg | A figure made of tiny glyphs and dots with a warm core on pure black; dark pill button with a circled arrow; very sparse layout | The hero's central object: the rook drawn as a dot-matrix figure with a Strawberry core; generous empty space around few objects |
| Modern Presentation Design.jpg | Giant numerals as the display element; small corner labels; floating pill captions on the numerals; soft color glow behind shapes | Results: giant numerals (2, 0, 1 of 3) at 110 px with small mono captions and pill labels for each configuration; a Strawberry glow behind the leading result |
| Zenixa.jpg | Big pills used as shapes (a row of rounded capsules); pill nav; a black card with 34 px radius; small dot tags over section titles; a striped globe | Pills as shapes: Shingo labels, limits and the run status are capsules; rounded cards with 34 px radii; a dot tag above each section title. The giant background wordmark is not adopted: it would compete with the hero object |
| download (2).jpg | Monospace nav with slashes; thin crosshair grid lines framing the page; a pixel or voxel figure; a status chip; a stats row with mono labels split by 1 px lines | The hero frame: 1 px grid lines at very low opacity with crosshair marks at the corners; mono labels for every figure; the ticker's facts in mono with separators |
| download (3).jpg | Header with the mark centered and links split left and right; a two-tone headline; a halftone dome with a warm glow; floating pill labels with colored dots | The symmetric header (rook centered, pill links split evenly); the two-tone H1; floating pills around the hero object, each with a status dot and real data |
| download (4).jpg | Strict mirror symmetry about the vertical axis; dotted figures reaching toward a glowing central object; a centered pill nav | Mirrored pills and arcs around the central rook; the evidence check and the human gate as two mirrored pills left and right of the hierarchy rings; the VERIFIED and WITHDRAWN cards mirrored |
| download (5).jpg | Light shapes curving in from both sides toward a centered icon tile; small pill tags over centered titles; rounded dark cards in grids with gradient fills; a round node on a soft halo | Concentric rings for "How it works" with a round director node on a halo at the center; tag pills over centered titles; gradient cards in even grids |

### Still not adopted

- No raster images, photographs, portraits, 3D renders or engravings: every shape is CSS or
  SVG generated in code.
- No third-party logos or logo strips.
- No hue outside ink, Stellar Strawberry and bone (no green, lime, blue, violet or white).
- No giant background wordmark and no glass blur over content.

## 2. Palette

Visual pass 2 keeps the three anchors and adds a small semantic set (section 2.1). Everything
below the anchors table still holds for ink, bone and Stellar Strawberry.


Three hues and nothing else, including charts, states, gradients, glows and the favicon.

| Token | Value | Role |
|---|---|---|
| Ink | `#142030` | Page background, text on Strawberry and on bone fills |
| Stellar Strawberry | `#FF5C8D` | Primary action, WITHDRAWN, warnings, glow, focus ring |
| Bone | `#EAE4D3` | Text, VERIFIED, lines, dots |

Gradients and glows are allowed when built only from these three hues by opacity or mixing.

| Token | Recipe |
|---|---|
| card | linear gradient from bone 8% over ink (top) to bone 4% over ink (bottom) |
| raised | bone 8% over ink (`#25303d`) |
| track | bone 13% over ink (`#303945`), bars and rings only, never under text |
| line | bone 14% over ink |
| line-strong | bone 38% over ink |
| muted text | bone 72% over ink (`#aeada5`) |
| berry-tint | Strawberry 13% over ink (`#33283c`) |
| glow | radial gradient, Strawberry at 30 to 45% to transparent; never under text |
| grid lines | bone at 6% opacity, 1 px |

### Contrast against the brightest background pixel

Every text color is checked against the brightest pixel it can sit on. For a card that is its
top edge (bone 8% over ink). No text sits over the glow.

| Text on brightest background | Ratio |
|---|---|
| bone on ink | 12.93:1 |
| ink on bone (VERIFIED, active pills) | 12.93:1 |
| ink on Strawberry (primary button, WITHDRAWN) | 5.60:1 |
| Strawberry on ink | 5.60:1 |
| bone on card top / raised (bone 8%) | 10.54:1 |
| muted on card top / raised | 5.94:1 |
| Strawberry on card top / raised | 4.57:1 |
| bone on berry-tint | 10.95:1 |
| Strawberry on berry-tint | 4.75:1 |
| muted on berry-tint | 6.17:1 |
| line-strong on ink (control borders, non-text) | 3.00:1 |

Strawberry on bone 12% would fall to 4.06:1, so no card gradient goes above bone 8%, and
Strawberry text never sits on the track tint.

### 2.1 Semantic colors (visual pass 2)

Four colors, each with one meaning, defined as Tailwind theme variables in `web/src/index.css`
(`--color-teal`, `--color-amber`, `--color-violet`, `--color-gold`, and a `-tint` of each at 16%
over ink). Every use also carries an icon or a word, so color is never the only signal.

| Token | Value | Meaning | Where |
|---|---|---|---|
| teal | `#3ED6B0` | Verified: a supported claim, a passed check | VERIFIED stamp, verified claim rows and cited lines, "Citation verified", the proof line in the hero, Contact and Sequence labels, the leading result |
| amber | `#FFA53D` | Withdrawn: a claim removed by the check, a warning | WITHDRAWN stamp, withdrawn rows, failed cited lines and their strikethrough, Warning labels, Limits |
| violet | `#A5A8FF` | The auditor, the second check | Audit verdict and status chips, Second check labels, the auditor node and ring, the recorded-run banner and pill |
| gold | `#F2CF5B` | Budget and money, used sparingly | Budget ring in the run strip, the budget meter and ledger bars, the money pill and ticker items, mean cost in Results, Control labels |

Strawberry stays the action color: the primary button, "Decision needed", "You decide", focus
rings and the hero glow.

Contrast, WCAG 2.x, computed against the brightest pixel each text can sit on:

| Color | as text on ink | as text on card top (bone 8%) | ink text on a fill of it | as text on its own tint | bone on its tint | muted on its tint |
|---|---|---|---|---|---|---|
| teal | 8.95:1 | 7.30:1 | 8.95:1 | 6.37:1 | 9.20:1 | 5.19:1 |
| amber | 8.37:1 | 6.82:1 | 8.37:1 | 6.17:1 | 9.53:1 | 5.37:1 |
| violet | 7.54:1 | 6.15:1 | 7.54:1 | 5.51:1 | 9.45:1 | 5.33:1 |
| gold | 10.83:1 | 8.83:1 | 10.83:1 | 7.41:1 | 8.84:1 | 4.99:1 |
| Strawberry | 5.60:1 | 4.57:1 | 5.60:1 | 4.75:1 (13% tint) | 10.95:1 | 6.17:1 |

Washes: soft radial gradients painted on the hero and on the poka-yoke, how-it-works and
results sections, so nothing extends past the page. Brightest wash pixels and the text over them:

| Wash (peak) | bone | muted | teal text |
|---|---|---|---|
| teal 12% | 10.08:1 | 5.68:1 | 6.98:1 |
| violet 12% | 10.35:1 | 5.83:1 | 7.17:1 |
| Strawberry 10% | 11.46:1 | 6.46:1 | 7.93:1 |
| amber 8% | 11.20:1 | 6.31:1 | 7.76:1 |

Hues per screen (accents, not counting ink and bone): hero teal, amber, violet, gold and the
Strawberry button (the four semantic pills and the action share the first screen; see
deviations); poka-yoke teal, gold, amber, violet; how it works violet, teal, Strawberry;
results teal and gold; run evidence teal, amber, violet.

## 3. Shape language, golden ratio and symmetry

- **Radii:** Fibonacci 13, 21, 34, 55 for cards and panels; full pills for navigation, buttons,
  tags and chips; circles for status dots, rings and progress.
- **Borders:** 1 px at bone 14% (or bone 38% on controls).
- **Depth:** the top-lit card gradient, and a Strawberry radial glow behind key objects only (the
  hero rook, the director node, the leading result).
- **Spacing** (margin, padding and gap only): 8, 13, 21, 34, 55, 89, 144 px.
- **Type:** 18, 29, 47, 76, 123 px since visual pass 2 (was 16, 26, 42, 68, 110). Each step is
  about 1.618 times the last. Body line height 1.618; display 1.1. Body weight 500, headings 900.
- **Layout:** two-column layouts are `1.618fr 1fr`; one central vertical axis; mirrored pairs.
- **Grids:** 2x3 or 3x2 or 3x1; never 5.
- **Mark:** the rook, 21 by 34 units, symmetric about x = 10.5. The hero draws it again as a dot
  matrix sampled from the same polygon.
- **Fonts (SIL OFL 1.1, self-hosted):** Nunito (variable) for headings, interface and body since
  visual pass 2; JetBrains Mono only for log lines, citations, line numbers and money.

## 4. Self-review

Screenshots at 1280 and 390 px of the landing (hero, hero object, poka-yoke, how it works,
results, full page) and of the run view (top, evidence, safeguards, approval), taken with
`npm run screenshots` into `web/screenshots-local/` (not committed) and compared with the nine
references.

### Round 1

| Question | Answer |
|---|---|
| Does the hero have a central object with depth and a glow? | Yes, but at 1280 by 900 it sat entirely below the fold: the three-line H1 and stacked buttons pushed it down. |
| Are cards and buttons visibly round? | Yes: 34 px cards, pill buttons, pill nav, pill tags. |
| Do pills and ticker exist? | Yes: four floating pills with real data (c1 verified, c2 withdrawn: quote_not_found, $0.188152 of $0.500000 cap, 60 slices read, 0 unread) and the ticker. |
| Is there a giant numeral? | Yes: 2, 0 and 1 at 110 px in Results. |
| One original design, not a copy? | Yes: the dot-matrix rook, the rings and the stamp cards appear in no reference. |
| Does anything look flat or empty? | The hero first screen had no object. The run strip's team diagram was a grey speck at 55 px. Poka-yoke cards in a row had different heights. On a phone the two gate pills stacked instead of mirroring, and the strip was three rows of pills. |

Fixes: H1 to two lines at 1280 (21ch), buttons side by side with the note centered under both,
smaller gaps, so the rook's crown shows on the first screen; a compact mode for the strip's rings
(nodes 2.6 times larger); fewer strip pills; poka-yoke cards stretch to equal heights; gate pills
side by side on phones; a larger glow behind the rings; root cause at 26 px.

### Round 2

| Question | Answer |
|---|---|
| Does the hero have a central object with depth and a glow? | Yes. The rook's crown, glow and arcs show on the first 1280 by 900 screen; the full object sits on the grid frame with crosshairs. |
| Are cards and buttons visibly round? | Yes, at both widths. |
| Do pills and ticker exist? | Yes. On phones the four pills stack under the rook instead of floating. |
| Is there a giant numeral? | Yes. |
| One original design, not a copy? | Yes. |
| Does anything look flat or empty? | Two small issues: on a phone the "Evidence check" pill wrapped inside its capsule, and claim pills ("Root cause rests on this") wrapped inside theirs. Fixed with no-wrap and smaller inner padding on phones. The long section gaps (144 px) read as calm at 1280, not empty. |

## 5. Deviations

- **Section titles not in the brief:** "Three configurations, the same cap" (Results), "What this
  does not show" (Limits), and the tag pills ("Real model runs, replayed", "Mistake-proofing",
  "Results, test split"). The brief gave no titles for these.
- **Prices per 1M tokens:** not shown; the recording files carry none.
- **Hierarchy legend:** the rings carry no text inside the SVG (it would shrink below 16 px on a
  phone). Model names sit in a 2x2 legend of rounded cards under the rings.
- **Cards 1:1.618:** the six safeguard cards hold more text than a 1.618:1 box fits at 1280, so
  they stretch to equal heights instead of keeping the ratio.
- **Strip pills:** "Recorded" moved out of the strip (the banner above says it) and "Synthetic
  incident" became "Synthetic", so the strip stays one row at 1280.
- **Run view section links** (the old tabs) are gone; the strip's "Decision needed" pill still
  jumps to the approval gate.
- **Live runs control:** only on the landing; the shorter run banner no longer repeats it.
- **No text below 16 px** anywhere, so the references' tiny corner labels are 16 px mono.
- **The 394 px overflow** at a 390 px viewport came from the WITHDRAWN stamp: its paused animation
  held the first keyframe (`scale(1.618)`), which reached 3.6 px past the right edge. The stamps
  now rest in their final state, the animation only plays on top, and each stamp scales from its
  inner side. No `overflow-x: hidden` was added; `npm run check:overflow` fails if the page is
  wider than 360 or 390 px.
- **Every recorded run:** a row of pill links under the stamp cards, so inc-01-run3 stays
  reachable from the landing.

## 6. Visual pass 2

Nunito replaces Space Grotesk; the type scale moves up one notch (18 px body); the semantic set
of section 2.1 adds color; washes sit behind the hero and three sections; the hero now states
what Rookwise is, for whom, and its proof point, with one large Strawberry action ("Watch a
recorded investigation") and one secondary ("See the results"). "Recorded run, not live" and
"Executes nothing" sit as pills right above the hero object.

Deviations in this pass:

- **Hues on the first screen:** the hero shows the Strawberry action plus teal, amber, gold and
  violet pills, five accents where the brief asks for at most four. Each pill marks a different
  meaning and the action color is Strawberry by rule; dropping one would hide a fact.
- **Live runs control:** removed from the hero. The "Recorded run, not live" pill carries the same
  fact next to the demo.
- **Labels:** no longer mono uppercase; they are Nunito 800 at body size. Stamps keep VERIFIED and
  WITHDRAWN in upper case.
- **Results count:** each count is one string ("2 of 3") so release/check_numbers.py finds it in
  the source; `::first-letter` keeps the count as the giant numeral.
