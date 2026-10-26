# Design direction

This file records what the web redesign took from the reference images, the palette with its
contrast ratios, the golden-ratio rules, and every place the build departs from the brief.

## 1. References

The images live in `design-refs/` at the repository root (gitignored, not shipped). No other
reference folder exists: `web/design-refs/` is absent, and `.claude/skills/stop-slop/references/`
holds Markdown only.

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

What each image shows (layout, density, type, color, motion, staging). All nine are still
images, so no motion is visible in any of them.

1. **AI Landing Page Design.jpg**: dark navy page; centered two-line sans headline with one accent word, a pill badge above it, a filled button beside an outline one; a wave graphic, a logo strip, a row of three dark glassy cards, then a 2x2 "how it works" grid of rounded cards with thin borders; medium density; the headline is staged first.
2. **Lapa Ninja (corporate landing)**: light page in one blue on white; engraving illustrations frame a large centered uppercase serif headline; a small logo with the nav at the left; a ticker band, then uneven text columns and a large statement paragraph; low density; the headline is staged first.
3. **Daniella.jpg**: pure black; a left-aligned two-line serif headline, a small grey sans line under it, a dark pill button with a circled arrow; dotted glyph art on the right; very sparse; the headline is staged first.
4. **Modern Presentation Design.jpg**: dark green gradient slides; giant numerals carry the display role, with tiny corner labels and short captions beside each figure; low density; the numbers are staged first.
5. **Zenixa.jpg**: light grey; a tight large sans headline at the left, a centered portrait, a giant wordmark behind it, pill nav, a row of pill shapes and a black rounded card for work samples; medium density; the portrait is staged first.
6. **download (2).jpg**: black; monospace nav with slashes; thin crosshair grid lines frame the page; left text hero with a lime filled button and an outline button; a voxel graphic at the right; a status chip; stats in a bordered row with mono labels; medium density; the headline is staged first.
7. **download (3).jpg**: near black; symmetric header with the logo centered and links split left and right; a centered two-tone headline (white, then grey); a white pill button; a dotted halftone dome in one warm color; floating pill labels; low density; the headline is staged first.
8. **download (4).jpg**: black; a centered pill nav; a centered two-tone headline over a mono sub line; a dotted pair of hands mirrored about the vertical axis around a glowing central object; strong symmetry; low density; the central object is staged first.
9. **download (5).jpg**: black; a centered headline over curved light shapes, a centered icon, a logo strip; centered section titles with small pill tags above them; grids of dark grey rounded cards in three and four columns; medium density; the headline is staged first.

### Principles taken

- One dark field with one warm accent (images 1, 3, 6, 7, 8, 9). Here: ink with Stellar Strawberry.
- Discipline of a single hue family (image 2 uses one blue on white). Here: three hues, tints by opacity only.
- A symmetric header: mark centered, links split evenly left and right (image 7).
- A centered hero with a two-tone headline, bright then muted (images 1, 7, 8).
- Mirroring about the vertical axis (image 8). Here: the VERIFIED and WITHDRAWN cards mirror each other.
- Mono labels and figures inside thin ruled rows (image 6). Here: labels, log lines and the results table.
- Large numerals with small captions (image 4). Here: the results figures.
- A small tag above each centered section title (image 9). Here: a mono kicker above each title.
- Even grids of rounded cards with thin borders (images 1, 9). Here: 2x3 only.
- Generous empty space around few elements (images 3, 7).

### Not taken

- No brand, logo, text, layout or asset from any image. The rook mark is drawn from scratch.
- No gradients, glows, wave shapes, halftone or dotted art, voxels, portraits, engravings, logo
  strips, tickers, giant background wordmarks or glass blur.
- No other hue: no navy, green, lime, blue, grey-blue or white.
- No light page (images 2, 5) and no left-aligned hero (images 3, 5, 6): the brief asks for a
  central axis.

### Where a reference conflicts with a hard rule

| Reference shows | Hard rule | What the build does |
|---|---|---|
| Card rows of three and four (images 1, 9) | Even grids, 2x3 or 3x2, never 5 | 2x3 for the six safeguards, 3 columns for the results table only |
| Tiny 10 to 12 px labels (images 4, 6) | Type scale 16, 26, 42, 68, 110 | No text below 16 px; labels are 16 px mono uppercase |
| Glow and gradient light (images 1, 8, 9) | Three hues, tints by opacity only | Flat ink with bone tints; Strawberry carries the light role |
| White and lime buttons (images 6, 7) | Primary is Strawberry with ink text | Strawberry fill, ink text |

## 2. Palette (hard rule)

Three hues and nothing else, including charts, states and the favicon.

| Token | Value | Role |
|---|---|---|
| Ink | `#142030` | Page background, text on Strawberry and on bone fills |
| Stellar Strawberry | `#FF5C8D` | Primary action, WITHDRAWN, warnings, focus ring |
| Bone | `#EAE4D3` | Text, VERIFIED, lines |

Tints, all by opacity of the three hues over ink:

| Token | Recipe | Flattened |
|---|---|---|
| surface | bone 5% over ink | `#1f2a38` |
| raised | bone 8% over ink | `#25303d` |
| track | bone 13% over ink | `#303945` |
| line | bone 14% | |
| line-strong | bone 38% | |
| muted text | bone 72% | `#aeada5` on ink |
| withdrawn tint | Strawberry 13% over ink | `#33283c` |

States:

- **Verified:** bone solid fill, ink text, a check icon, the label VERIFIED.
- **Withdrawn:** Strawberry solid fill, ink text, a cross icon, the label WITHDRAWN, and a
  strikethrough on the quote that failed.
- Strawberry appears only on ink or ink tints, never as text on bone. Text on a Strawberry fill is ink.
- Dark is the only theme. The theme switch is gone.

### Contrast (WCAG 2.x relative luminance, computed)

| Text on background | Ratio | Use |
|---|---|---|
| bone on ink | 12.93:1 | Body text |
| ink on bone | 12.93:1 | VERIFIED stamp |
| Strawberry on ink | 5.60:1 | Strawberry text, focus ring |
| ink on Strawberry | 5.60:1 | Primary button, WITHDRAWN stamp |
| bone on surface | 11.43:1 | Panel text |
| bone on raised | 10.54:1 | Log lines |
| bone on withdrawn tint | 10.95:1 | Withdrawn claim text |
| Strawberry on surface | 4.95:1 | Warnings inside panels |
| Strawberry on raised | 4.57:1 | Strawberry inside log blocks |
| Strawberry on withdrawn tint | 4.75:1 | Reason line on a withdrawn claim |
| muted (bone 72%) on ink | 7.29:1 | Secondary text |
| muted on raised | 6.28:1 | Secondary text in log blocks |
| muted on track | 5.62:1 | Worst case for secondary text |
| line-strong (bone 38%) on ink | 3.00:1 | Input and control borders (non-text, 3:1) |

Every text pair clears 4.5:1. Strawberry on the track tint would be 3.99:1, so the build never
puts Strawberry text on track; Strawberry on track appears only as a bar fill.

## 3. Golden ratio and symmetry

- **Spacing** (margin, padding and gap only): 8, 13, 21, 34, 55, 89, 144 px. Each step divided by
  the previous is within 0.01 of 1.618 from 13 up. Section rhythm is 89 and 144.
- **Type:** 16, 26, 42, 68, 110 px. Body line height 1.618; display line height 1.1.
- **Layout:** two-column layouts are `1.618fr 1fr`. Cards are 1:1.618 where the content allows.
- **Axis:** one central vertical axis. Header: rook mark centered, nav split evenly left and right.
  The hero is centered. The VERIFIED and WITHDRAWN cards mirror each other about the axis.
- **Grids:** 2x3 or 3x2. Mobile stacks on the axis.
- **Mark:** an original geometric rook, 21 by 34 units (1:1.619), symmetric about its vertical axis.
- **Fonts (SIL OFL 1.1, self-hosted):** Space Grotesk for display and text, JetBrains Mono for
  labels, figures and log lines.

`web/src/lib/scale.ts` holds the tokens, `web/src/lib/scale.test.ts` checks the ratios and that
`index.css` declares the same values, and `npm run check:scale` lists margin, padding and gap
values outside the token set (it reports and never fails).

## 4. Deviations

Filled in at the end of the redesign; see section 5 of the final report in the commit history.
