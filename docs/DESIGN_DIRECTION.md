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

## 2. Palette (hard rule)

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

## 3. Shape language, golden ratio and symmetry

- **Radii:** Fibonacci 13, 21, 34, 55 for cards and panels; full pills for navigation, buttons,
  tags and chips; circles for status dots, rings and progress.
- **Borders:** 1 px at bone 14% (or bone 38% on controls).
- **Depth:** the top-lit card gradient, and a Strawberry radial glow behind key objects only (the
  hero rook, the director node, the leading result).
- **Spacing** (margin, padding and gap only): 8, 13, 21, 34, 55, 89, 144 px.
- **Type:** 16, 26, 42, 68, 110 px. Body line height 1.618; display 1.1.
- **Layout:** two-column layouts are `1.618fr 1fr`; one central vertical axis; mirrored pairs.
- **Grids:** 2x3 or 3x2 or 3x1; never 5.
- **Mark:** the rook, 21 by 34 units, symmetric about x = 10.5. The hero draws it again as a dot
  matrix sampled from the same polygon.
- **Fonts (SIL OFL 1.1, self-hosted):** Space Grotesk and JetBrains Mono.

## 4. Self-review

Filled in from the screenshots in `web/screenshots-local/` (not committed).

## 5. Deviations

Filled in at the end of the redesign.
