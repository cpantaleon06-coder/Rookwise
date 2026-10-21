# Rookwise web: design system and screen inventory

Status: design only, written on 2026-10-21. No framework is chosen and no code exists in `web/` yet. Everything here describes the landing page and the run view against API contract v1 ([docs/api.md](../docs/api.md), models in `core/api/models.py`, schemas in `docs/api/schemas/`). Where a screen needs something the contract does not carry, it is flagged as a missing field (M1 to M16, listed in section 3.5); the contract itself is not changed here.

Reference images live in `design-refs/` on the author's machine. That folder is gitignored and nothing in it is copied into `web/`: no image, logo, illustration or brand mark. Only layout, typography, color and spacing principles were taken from it, and each principle below names the image it came from.

## 1. Principles

### 1.1 Who the user is

A team of a few engineers that runs its own services and carries the pager itself (docs/ARCHITECTURE.md, "Value proposition and target user"). The person in front of the screen was woken at 3 a.m., is reading on a laptop or a phone, is tired, and does not trust an agent's answer or an agent's bill by default. They will not read a paragraph to find out whether the run is about to cost more than they agreed, or whether a claim is backed by a real log line.

### 1.2 What the screen must make obvious

At any moment of a run, without scrolling or opening anything, the user can answer three questions:

1. **How much has this cost against the cap?** Spent, reserved (`held_usd`) and the cap are always visible in the sticky run header, as numbers and as a meter. Predicted versus real sits one glance away in the budget panel.
2. **Which claims are verified?** Every claim in the diagnosis shows its status in words and with an icon: "Verified" when every citation passed the deterministic check, "Withdrawn" with its reason code when it did not. Withdrawn claims are listed, never hidden (D3).
3. **What needs a decision from me?** When the run waits for the human, a "Decision needed" chip appears in the run header and the approval gate sits at the top of the main column. Nothing else on the page uses the decision color.

### 1.3 Layout and visual principles, and where they came from

| # | Principle | Source image (`design-refs/`) |
|---|---|---|
| P1 | **Color is reserved for state.** The interface is neutral (near-black or paper white); the only colored things are statuses: verified, withdrawn or stopped, decision needed, recorded. The primary action is an inverted neutral pill (light on dark, dark on light), never a status color, so "green" always means verified and never "click here". | `download (3).jpg` and `download (4).jpg` (solid white pill as the one call to action on a dark page); `download (2).jpg` (the single accent is spent on a status label, "all systems operational", and one button) |
| P2 | **Mono uppercase for labels, metadata and machine values.** Small uppercase monospace labels sit above the values they name; ids, line numbers, quotes from logs and money use a monospace face with tabular figures. | `download (2).jpg` (mono uppercase nav and stat labels over large numbers) |
| P3 | **Stat row with hairline dividers.** Key numbers sit in a row of equal cells separated by 1 px vertical rules: label above, value below, no boxes around each number. This is the budget strip in the run header. | `download (2).jpg` (the three stats at the bottom of the hero) |
| P4 | **One big number, small annotations.** In the budget panel, spent is the one large numeral; reserved, predicted and the cap are small pill annotations around it, not competing numbers. | `Modern Presentation Design _ Graphic Design & Data Visualization.jpg` (a giant numeral with small pill tags pinned to it, and corner labels for metadata) |
| P5 | **Every number carries its provenance.** A number is followed by a small muted caption saying where it comes from or when it was measured ("as of run_..., event 41", "from benchmark, test split"). On the landing, a number that does not exist yet is a visible placeholder, not a guess. | `Corporate Landing Pages_ 1097 Examples & Inspiration _ Lapa Ninja.jpg` (a large statement with a figure, followed by a small grey "as of" caption) |
| P6 | **Serif display, sans everything else.** One serif face for the landing headline only (two short lines, left aligned, muted sans subline under it). The run view uses no serif. | `Daniella.jpg` (serif two-line headline, muted sans subtext, small pill button, copy left and visual right) |
| P7 | **Two-tone sentences for hierarchy.** A heading can carry its main clause in the text color and its continuation in the muted color, instead of adding a second, smaller heading. | `Zenixa – UI_UX Case Study for Creative Agency.jpg` and `download (3).jpg` (sentences that switch from black or white to grey mid-line) |
| P8 | **Dot plus word for status chips.** A status chip is a small dot in the status color plus an uppercase word. The word carries the meaning, so color is never the only signal. | `download (3).jpg` (floating chips: colored dot plus uppercase label) |
| P9 | **Eyebrow, heading, one line, cards.** Every landing section opens with a small eyebrow chip, a centered or left heading, one line of explanation, then a row of equal cards with a 1 px border and no heavy shadow. Generous vertical space between sections. | `download (5).jpg` (eyebrow chip, H2, one-line sub, card row; repeated with even spacing) and `AI Landing Page Design.jpg` (three-up feature cards with hairline borders, sections split by a hairline rule) |
| P10 | **Steps as a numbered row.** "How it works" is a row of numbered step cards (four or five), read left to right, each with a title and one sentence. | `download (5).jpg` ("How it Works" four step cards) and `download (4).jpg` (a row of small process icons under the hero) |
| P11 | **Visible structure in the run view.** Panels align to a visible grid with 1 px rules; the page looks like an instrument, not a marketing page. Crosshair marks and decorative grid lines are not copied; only the alignment discipline is. | `download (2).jpg` (grid lines framing hero and stats) |
| P12 | **Light theme as a single ink on paper.** The light theme is one dark ink on an off-white paper background, with status colors as the only other hues. | `Corporate Landing Pages_ 1097 Examples & Inspiration _ Lapa Ninja.jpg` (one ink color on white) and `Zenixa – UI_UX Case Study for Creative Agency.jpg` (light grey ground, black type, black pill buttons) |

Rejected on purpose, although several references use them:

- **Logo strips and "trusted by" rows** (`AI Landing Page Design.jpg`, `download (2).jpg`, `download (5).jpg`, `Zenixa – UI_UX Case Study for Creative Agency.jpg`). Rookwise has no customers to show. Nebius Token Factory and NVIDIA Nemotron are named in text where they are used, without their logos (trademark use is a separate question, see section 6).
- **Testimonials, star ratings and customer counts** (`AI Landing Page Design.jpg`, `Zenixa – UI_UX Case Study for Creative Agency.jpg`). Nothing backs them.
- **Glow gradients, 3D renders and particle art as hero visuals** (most references). They cost load time on a phone at 3 a.m. and say nothing about a run. The landing hero visual is a static excerpt of a run view instead (a real claim with its citation, from a recorded run, once one is chosen).

### 1.4 Tone of the copy

- Plain and specific. Say what happened, with the number and its unit: "Stopped at the cap: spent $0.100000 of $0.100000." Not "Budget issue detected".
- Calm. No exclamation marks, no "oops", no urgency the data does not justify.
- Short. A status line is one sentence. An explanation is at most three.
- Honest about limits. When something is synthetic, estimated, partial, recorded or unverified, the copy says so in the same sentence.
- The user decides. Copy never implies Rookwise will act on the user's systems; v1 executes nothing (docs/ARCHITECTURE.md, "The human approval gate").
- English only, no em dashes (repo rule); use parentheses or a full stop instead.

## 2. Tokens

Names are framework-neutral. They can become CSS custom properties (`--color-bg`) or any token format later.

### 2.1 Color

Dark is designed first (the 3 a.m. case); light is a full theme, not an afterthought. The page follows `prefers-color-scheme`, with a manual override (open question 1).

| Token | Role | Dark | Light |
|---|---|---|---|
| `color.bg` | Page background | `#0B0F14` | `#F6F6F3` |
| `color.surface` | Panels and cards | `#121821` | `#FFFFFF` |
| `color.raised` | Inputs, rows on hover, nested cards | `#1A2230` | `#EDEEEA` |
| `color.border` | Decorative hairlines only (never the only cue for meaning) | `#2A3442` | `#D7DAD3` |
| `color.border-strong` | Input borders, meter outlines, anything that must be seen | `#6B7889` | `#7A828C` |
| `color.text` | Body and headings | `#E8EDF2` | `#111418` |
| `color.muted` | Secondary text, captions, provenance | `#A3AFBC` | `#525B66` |
| `color.primary` | Primary button fill (inverted neutral) | `#E8EDF2` | `#111418` |
| `color.on-primary` | Text on the primary button | `#0B0F14` | `#F6F6F3` |
| `color.focus` | Focus ring | `#7CC4FF` | `#1F5FD1` |
| `color.ok` | Verified, accepted, finished | `#5BD68A` | `#17713F` |
| `color.ok-tint` | Background of a verified chip or row | `#0F2A1C` | `#E3F3E9` |
| `color.warn` | Decision needed; budget at 80 percent of the cap or more | `#F2C14E` | `#835500` |
| `color.warn-tint` | Background of the approval gate and decision chip | `#2E2510` | `#FBF0D6` |
| `color.danger` | Withdrawn claim, budget stop, failed, refused | `#FF8A80` | `#B42318` |
| `color.danger-tint` | Background of a withdrawn row or stop banner | `#331816` | `#FBE7E5` |
| `color.info` | Recorded mode | `#B3AEFF` | `#4B3FC4` |
| `color.info-tint` | Background of the recorded banner | `#1F1C3D` | `#ECEAFD` |
| `color.track` | Empty part of a meter | `#2A3442` | `#D7DAD3` |

Rules:

- Status colors appear only with a word and an icon (P8). A withdrawn claim reads "Withdrawn: quote_not_found", never just a red border.
- `color.warn` is used for "decision needed" and for the budget meter at 80 percent of the cap or more, and nothing else.
- Live mode has no color of its own: it is the word "Live" with a neutral dot. Recorded mode is `color.info` everywhere it appears.

### 2.2 Contrast ratios

Computed with the WCAG 2.x relative luminance formula. Target: AA, which is 4.5:1 for normal text and 3:1 for large text and for non-text UI (borders that carry meaning, focus rings, meter fills). Every status text size in this system is normal text, so 4.5:1 applies to all text pairs.

Dark theme:

| Foreground | Background | Ratio | Needed | Result |
|---|---|---|---|---|
| text `#E8EDF2` | bg `#0B0F14` | 16.32 | 4.5 | Pass |
| text `#E8EDF2` | surface `#121821` | 15.13 | 4.5 | Pass |
| text `#E8EDF2` | raised `#1A2230` | 13.55 | 4.5 | Pass |
| muted `#A3AFBC` | bg `#0B0F14` | 8.62 | 4.5 | Pass |
| muted `#A3AFBC` | surface `#121821` | 7.99 | 4.5 | Pass |
| muted `#A3AFBC` | raised `#1A2230` | 7.16 | 4.5 | Pass |
| ok `#5BD68A` | bg `#0B0F14` | 10.46 | 4.5 | Pass |
| ok `#5BD68A` | surface `#121821` | 9.70 | 4.5 | Pass |
| ok `#5BD68A` | raised `#1A2230` | 8.69 | 4.5 | Pass |
| warn `#F2C14E` | bg `#0B0F14` | 11.45 | 4.5 | Pass |
| warn `#F2C14E` | surface `#121821` | 10.62 | 4.5 | Pass |
| warn `#F2C14E` | raised `#1A2230` | 9.51 | 4.5 | Pass |
| danger `#FF8A80` | bg `#0B0F14` | 8.42 | 4.5 | Pass |
| danger `#FF8A80` | surface `#121821` | 7.81 | 4.5 | Pass |
| danger `#FF8A80` | raised `#1A2230` | 6.99 | 4.5 | Pass |
| info `#B3AEFF` | bg `#0B0F14` | 9.53 | 4.5 | Pass |
| info `#B3AEFF` | surface `#121821` | 8.84 | 4.5 | Pass |
| info `#B3AEFF` | raised `#1A2230` | 7.92 | 4.5 | Pass |
| on-primary `#0B0F14` | primary `#E8EDF2` | 16.32 | 4.5 | Pass |
| ok `#5BD68A` | ok-tint `#0F2A1C` | 8.35 | 4.5 | Pass |
| text `#E8EDF2` | ok-tint `#0F2A1C` | 13.03 | 4.5 | Pass |
| warn `#F2C14E` | warn-tint `#2E2510` | 9.01 | 4.5 | Pass |
| text `#E8EDF2` | warn-tint `#2E2510` | 12.84 | 4.5 | Pass |
| danger `#FF8A80` | danger-tint `#331816` | 7.17 | 4.5 | Pass |
| text `#E8EDF2` | danger-tint `#331816` | 13.89 | 4.5 | Pass |
| info `#B3AEFF` | info-tint `#1F1C3D` | 8.06 | 4.5 | Pass |
| text `#E8EDF2` | info-tint `#1F1C3D` | 13.80 | 4.5 | Pass |
| border-strong `#6B7889` (non-text) | bg `#0B0F14` | 4.28 | 3.0 | Pass |
| border-strong `#6B7889` (non-text) | surface `#121821` | 3.97 | 3.0 | Pass |
| border-strong `#6B7889` (non-text) | raised `#1A2230` | 3.55 | 3.0 | Pass |
| focus `#7CC4FF` (non-text) | bg `#0B0F14` | 10.25 | 3.0 | Pass |
| focus `#7CC4FF` (non-text) | surface `#121821` | 9.50 | 3.0 | Pass |
| focus `#7CC4FF` (non-text) | raised `#1A2230` | 8.51 | 3.0 | Pass |
| meter fill ok `#5BD68A` | track `#2A3442` | 6.85 | 3.0 | Pass |
| meter fill warn `#F2C14E` | track `#2A3442` | 7.50 | 3.0 | Pass |
| meter fill danger `#FF8A80` | track `#2A3442` | 5.51 | 3.0 | Pass |
| meter fill neutral `#E8EDF2` | track `#2A3442` | 10.69 | 3.0 | Pass |

Light theme:

| Foreground | Background | Ratio | Needed | Result |
|---|---|---|---|---|
| text `#111418` | bg `#F6F6F3` | 17.06 | 4.5 | Pass |
| text `#111418` | surface `#FFFFFF` | 18.47 | 4.5 | Pass |
| text `#111418` | raised `#EDEEEA` | 15.85 | 4.5 | Pass |
| muted `#525B66` | bg `#F6F6F3` | 6.37 | 4.5 | Pass |
| muted `#525B66` | surface `#FFFFFF` | 6.89 | 4.5 | Pass |
| muted `#525B66` | raised `#EDEEEA` | 5.91 | 4.5 | Pass |
| ok `#17713F` | bg `#F6F6F3` | 5.59 | 4.5 | Pass |
| ok `#17713F` | surface `#FFFFFF` | 6.05 | 4.5 | Pass |
| ok `#17713F` | raised `#EDEEEA` | 5.19 | 4.5 | Pass |
| warn `#835500` | bg `#F6F6F3` | 5.94 | 4.5 | Pass |
| warn `#835500` | surface `#FFFFFF` | 6.43 | 4.5 | Pass |
| warn `#835500` | raised `#EDEEEA` | 5.52 | 4.5 | Pass |
| danger `#B42318` | bg `#F6F6F3` | 6.07 | 4.5 | Pass |
| danger `#B42318` | surface `#FFFFFF` | 6.57 | 4.5 | Pass |
| danger `#B42318` | raised `#EDEEEA` | 5.64 | 4.5 | Pass |
| info `#4B3FC4` | bg `#F6F6F3` | 6.91 | 4.5 | Pass |
| info `#4B3FC4` | surface `#FFFFFF` | 7.48 | 4.5 | Pass |
| info `#4B3FC4` | raised `#EDEEEA` | 6.42 | 4.5 | Pass |
| on-primary `#F6F6F3` | primary `#111418` | 17.06 | 4.5 | Pass |
| ok `#17713F` | ok-tint `#E3F3E9` | 5.26 | 4.5 | Pass |
| text `#111418` | ok-tint `#E3F3E9` | 16.06 | 4.5 | Pass |
| warn `#835500` | warn-tint `#FBF0D6` | 5.68 | 4.5 | Pass |
| text `#111418` | warn-tint `#FBF0D6` | 16.30 | 4.5 | Pass |
| danger `#B42318` | danger-tint `#FBE7E5` | 5.53 | 4.5 | Pass |
| text `#111418` | danger-tint `#FBE7E5` | 15.53 | 4.5 | Pass |
| info `#4B3FC4` | info-tint `#ECEAFD` | 6.32 | 4.5 | Pass |
| text `#111418` | info-tint `#ECEAFD` | 15.61 | 4.5 | Pass |
| border-strong `#7A828C` (non-text) | bg `#F6F6F3` | 3.59 | 3.0 | Pass |
| border-strong `#7A828C` (non-text) | surface `#FFFFFF` | 3.89 | 3.0 | Pass |
| border-strong `#7A828C` (non-text) | raised `#EDEEEA` | 3.34 | 3.0 | Pass |
| focus `#1F5FD1` (non-text) | bg `#F6F6F3` | 5.36 | 3.0 | Pass |
| focus `#1F5FD1` (non-text) | surface `#FFFFFF` | 5.81 | 3.0 | Pass |
| focus `#1F5FD1` (non-text) | raised `#EDEEEA` | 4.98 | 3.0 | Pass |
| meter fill ok `#17713F` | track `#D7DAD3` | 4.28 | 3.0 | Pass |
| meter fill warn `#835500` | track `#D7DAD3` | 4.55 | 3.0 | Pass |
| meter fill danger `#B42318` | track `#D7DAD3` | 4.65 | 3.0 | Pass |
| meter fill neutral `#111418` | track `#D7DAD3` | 13.07 | 3.0 | Pass |

`color.border` is decorative and is not held to 3:1; anything that carries meaning uses `color.border-strong`. Any new color pair must be added to these tables with its computed ratio before it ships.

### 2.3 Type

Free fonts only, all under the SIL Open Font License 1.1 (free to use, embed and self-host, including commercially; the license text ships with the font files, and the fonts cannot be sold on their own).

| Use | Font | License | Why |
|---|---|---|---|
| UI and body | Inter (variable) | SIL OFL 1.1 | Legible at small sizes; has tabular figures (`font-feature-settings: "tnum"`) |
| Mono: labels, ids, money, line numbers, log quotes | JetBrains Mono | SIL OFL 1.1 | Clear `0` versus `O` and `1` versus `l`, which matters when reading quotes from logs |
| Display: landing headline only | Source Serif 4 | SIL OFL 1.1 | P6; one serif moment on the landing, never in the run view |

Fallback stacks: `Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`; `"JetBrains Mono", ui-monospace, "Cascadia Mono", Menlo, Consolas, monospace`; `"Source Serif 4", Georgia, serif`. Use `font-display: swap`. Self-hosting versus a font CDN is open question 2.

Scale (ratio about 1.25, base 16 px; rem assumes a 16 px root and must scale with the user's browser setting):

| Token | Size / line height | Weight | Font | Use |
|---|---|---|---|---|
| `type.display` | 56 / 60 px (40 / 44 at phone width) | 500 | Source Serif 4 | Landing headline |
| `type.h1` | 32 / 40 | 600 | Inter | Page title, diagnosis root cause |
| `type.h2` | 24 / 32 | 600 | Inter | Section and panel titles |
| `type.h3` | 20 / 28 | 600 | Inter | Card titles, claim text in the evidence view |
| `type.body` | 16 / 24 | 400 | Inter | Body, chat |
| `type.small` | 14 / 20 | 400 | Inter | Secondary text, feed rows |
| `type.label` | 12 / 16, uppercase, letter spacing 0.06em | 500 | JetBrains Mono | P2 labels, chips, column headers |
| `type.number-xl` | 40 / 44 | 500 | JetBrains Mono | Spent in the budget panel (P4) |
| `type.number` | 16 / 24 | 500 | JetBrains Mono | Money and counts elsewhere |
| `type.code` | 14 / 20 | 400 | JetBrains Mono | Quotes, line numbers, ids |

Nothing smaller than 12 px. Body text lines stay under about 75 characters.

### 2.4 Spacing

4 px base: `space.1` 4, `space.2` 8, `space.3` 12, `space.4` 16, `space.5` 24, `space.6` 32, `space.7` 48, `space.8` 64, `space.9` 96, `space.10` 128.

- Page gutter: 16 px at phone width, 24 px at tablet, 32 px from 1024 px.
- Panel padding: 16 px (phone) or 24 px.
- Gap between panels in the run view: 16 px. Between landing sections: 96 px (64 px at phone width), per P9.
- Run view grid from 1024 px: 12 columns, 24 px gutters; main column 8, side column 4. Max content width 1440 px.

### 2.5 Radii

`radius.sm` 6 px (inputs, code blocks, quote boxes), `radius.md` 10 px (cards, claim rows), `radius.lg` 16 px (panels, approval gate), `radius.pill` 999 px (buttons, chips, the stat pills of P4). Buttons are pills (P1, from `download (3).jpg`, `download (4).jpg` and `Zenixa – UI_UX Case Study for Creative Agency.jpg`).

### 2.6 Elevation

No drop shadows in the run view; separation is a 1 px `color.border` and a surface step. One exception: an open drawer or dialog uses a shadow and a backdrop.

### 2.7 Motion

| Token | Value | Use |
|---|---|---|
| `motion.fast` | 120 ms | Hover, press, focus ring |
| `motion.base` | 200 ms | Chip and panel state changes, meter width |
| `motion.slow` | 320 ms | Drawer open and close |
| `motion.ease` | `cubic-bezier(0.2, 0, 0, 1)` | All of the above |

Motion only confirms a change; it never decorates. New feed rows appear without sliding. The live dot does not pulse. Under `prefers-reduced-motion: reduce` every duration is 0 except opacity fades of at most 120 ms. The replay timing of a recorded run is data, not animation, and is unchanged.

## 3. Screens

Field names below are the contract's (docs/api.md, `core/api/models.py`). "Event" means an SSE event `type`; "view" means a GET response.

### 3.1 (a) Landing page

**Purpose.** In ten seconds: what Rookwise does, the two promises it keeps (claims checked by code, a budget set before the run), and the two ways to try it (watch a recorded run for free, or start one live run). It must make no claim the code cannot back (section 4).

**Data.** `GET /api/v1/modes` (`ModesView`) on load. Nothing else from the API.

**Components, top to bottom (P9 rhythm):**

1. **Header.** Text wordmark "Rookwise" (no logo exists; open question 3), links: "How it works", "Source on GitHub". At phone width the links collapse into a menu button.
2. **Hero** (P6, left aligned). Serif headline of two short lines, one muted sans paragraph, two buttons:
   - "Watch a recorded run" (primary, P1). Starts `POST /runs` with `mode: "recorded"` and the `recording_id` of the first `ModesView.recordings[]` item. Hidden when `recordings` is empty, replaced by "No recorded run is published yet."
   - "Start a live run" (secondary, outline). Enabled only when the `modes[]` item with `mode: "live"` has `available: true`. Otherwise disabled, with its `detail` as the visible reason under it (for example the visitor limit).
   - On the right (stacked under the copy at phone width): a static excerpt of a run view showing one verified claim with its citation and one withdrawn claim with its reason. Built from a recorded run once one is chosen; until then a placeholder box labelled "Run excerpt: TBD from the recorded demo".
3. **Live demo limits** (P3 stat row, mono labels). Cells: "Per run" `live_caps.max_usd_per_run`; "Per day, all visitors" `live_caps.max_usd_per_day`; "Spent today" `live_caps.spent_usd_today`; "Your live runs today" `live_caps.visitor_runs_today` of `live_caps.max_runs_per_visitor_per_day`. Caption (P5): "Live runs call NVIDIA Nemotron models on Nebius Token Factory and cost real credits. Recorded runs cost nothing."
4. **Recorded runs.** One card per `recordings[]`: `title`, `goal`, "Synthetic incident" chip when `simulated_case` is true, "Cost when recorded: $`spent_usd`", button "Watch". Missing: when it was recorded and which incident and category (M15).
5. **How it works** (P10). Five numbered step cards condensed from docs/ARCHITECTURE.md, "What Rookwise does, end to end": 1 You pick the evidence and set a cap. 2 Cheap models read the logs in slices and cite lines. 3 A strong model writes the diagnosis. 4 Code checks every citation; unsupported claims are withdrawn and listed. 5 An independent auditor reviews, and you decide. v1 executes nothing.
6. **What you can check** (three cards, P9): "Every claim cites a line" (source, lines, quote; checked by `core/evidence.py`, no model); "A budget set before the run" (the ledger reserves money before each call and refuses calls that do not fit; predicted versus real is reported); "You decide" (approving records the decision and runs nothing).
7. **Benchmark** (section 4 rules). A table with the three configurations, (a) hierarchy, (b) single large model, (c) single small model, and the columns "Diagnosis correct (test split)", "Real cost", "Predicted versus real". Every cell reads "TBD from benchmark" until `benchmarks/` has produced the numbers. Caption: "6 synthetic incidents, 3 dev and 3 test, 2 runs each. Test results are reported apart from dev."
8. **Limits** (plain list): synthetic corpus; v1 executes nothing; three live smoke runs so far; numbers above appear only once measured.
9. **Footer.** MIT license, link to the repository, "Built for the Nebius x NVIDIA Global AI Hackathon 2026" (track not decided, so no track name), text credits for Nebius Token Factory, NVIDIA Nemotron and Tavily, no logos.

**Live intake (from "Start a live run").** A dialog with:

- Evidence: which incident to investigate. The contract has no field for it (M9); `CreateRunRequest` carries a free-text `goal` only.
- Cap: `budget_usd`, a six-decimal string, prefilled (default value is open question 6) and validated to be at most `live_caps.max_usd_per_run`. A 422 with `refusal: run_cap_exceeded` shows inline under the field.
- Copy above the button: "This run costs real credits, up to the cap you set. You have 1 live run per day."
- Submit sends `POST /runs` with `mode: "live"`, a fresh `Idempotency-Key` header and `credentials: "include"`. 201 opens the run view; 429 and 503 open the refusal state (3.4.2).

### 3.2 (b) Run view

**Purpose.** Watch one run from intake to decision, and know at every moment the cost against the cap, which claims are verified and what needs a decision (1.2).

**Data.** On open: `GET /runs/{run_id}` (`RunView`), then the SSE stream at `RunView.events_url` (`new EventSource(url, {withCredentials: true})`). Snapshots on open and after a reconnect: `GET /org` (`OrgChart`), `GET /ledger` (`LedgerView`), `GET /messages` (`ChatMessageList`), `GET /tasks` (`TaskList`). After `run_finished`: `GET` `package_url` (`DeliveryPackage`). Events are deduplicated by `id` and applied in `seq` order; every payload is a full snapshot, so applying one twice is harmless (docs/api.md, "Ordering and idempotency").

**Layout.** DOM order equals visual order: run header, main column, side column.

```
+---------------------------------------------------------------+
| [Recorded banner, recorded runs only]                         |
| RUN HEADER (sticky): mode | status | goal | spent/reserved/cap |
|                    meter | Decision needed chip | Cancel       |
+---------------------------------------+-----------------------+
| MAIN (8 cols)                         | SIDE (4 cols, sticky) |
|  Approval gate (when waiting)         |  Budget panel         |
|  Diagnosis and evidence               |  Chat with director   |
|  Team (org chart)                     |                       |
|  Live feed                            |                       |
+---------------------------------------+-----------------------+
```

#### 3.2.1 Run header (sticky)

| Element | Data |
|---|---|
| Mode chip: "Recorded" (`color.info`) or "Live" (neutral dot) | `RunView.mode`; every event's envelope `mode` |
| Status: Queued, Planning, Waiting for you, Running, Finished, Partial, Failed, Cancelled | `RunView.status`; terminal events `run_finished.status` and `.partial`, `run_failed` |
| Goal, one line, truncated with the full text on focus or hover | `RunView.goal` or `run_started.goal` |
| "Synthetic incident" chip | `RunView.simulated_case` |
| Budget strip (P3): Spent, Reserved, Cap, and a meter | `budget_update.spent_usd`, `.held_usd`, `.cap_usd` (first values from `RunView.spent_usd`, `.held_usd`, `.caps.run_usd`) |
| "Decision needed" chip (`color.warn`), a link to the gate | `RunView.status == "awaiting_approval"` (plan approval); remediation approval is missing (M6) |
| Cancel button (live only, while queued, planning, waiting or running) | `POST /runs/{run_id}/cancel`; confirm dialog "Stop the run? Calls in flight are charged; nothing else is spent." No pause or resume control (D7) |
| Jump links: Decision, Evidence, Team, Feed, Budget, Chat | Anchors |

The meter shows spent (solid) and reserved (hatched) on the track, with the cap as the end. Fill is neutral below 80 percent of the cap, `color.warn` from 80 percent, `color.danger` on a stop. Spent can pass the cap when a call's real usage exceeds its reservation (docs/ARCHITECTURE.md, "Cost of a call"); the meter then shows a danger overflow mark past the end and the strip says "over the cap by $0.000412". Comparisons use integer micro-USD parsed from the strings, never JavaScript floats (docs/api.md, "Conventions").

#### 3.2.2 Approval gate

Two gates exist in the product; the contract has one.

- **Plan approval** (in the contract). Shown while `RunView.status == "awaiting_approval"`. Content: the director's latest `message` (the plan in prose, which ends in "Approve?"). Controls: "Approve plan" (primary), "Reject plan" (secondary), an optional note (`ApprovalRequest.note`, at most 2000 characters). Sends `POST /runs/{run_id}/approval` with `approved` and `note`; 202 returns the `RunView`. A structured plan (blocks, tasks, the sources each reads, the predicted cost of the plan) is missing (M7). Note from docs/api.md, "Not in core yet": core does not wait for approval today.
- **Remediation approval** (not in the contract, M6). After the audit, the remediation plan's steps are shown, each with `action`, `why`, `risk` and a "Reversible" or "Not reversible" chip, followed by "Approve remediation plan" and "Reject". The copy above the buttons always reads: "Approving records your decision. Rookwise runs nothing on your systems." Hidden when the diagnosis is inconclusive (3.4.3).

Recorded runs: the gate is read-only. The buttons are replaced by "Recorded run: decisions cannot be changed" and, when available, the recorded decision. The contract has no event for the decision (M8); `DeliveryPackage.decisions` gives the strings after the run.

The gate is `color.warn-tint` with a `color.warn` left rule and the label "DECISION NEEDED". When it appears, focus is not moved; the polite live region announces "Decision needed: approve or reject the plan" (section 5).

#### 3.2.3 Diagnosis and evidence view

**Purpose.** Show the root cause and, for every claim, whether code verified its citations.

Components:

1. **Diagnosis header.** Root cause (`type.h1`), category chip (for example `dependency_latency`), and a count line: "7 claims: 5 verified, 2 withdrawn".
2. **Root-cause claims first.** Claims whose id is in `root_cause_claim_ids` get a "Root cause rests on this" label.
3. **Claim row.** Status chip (P8: dot plus "VERIFIED" in `color.ok`, or "WITHDRAWN" in `color.danger`), claim text, then each citation as a quote box: `source_id` and `L{line_start}` to `L{line_end}` in `type.label`, the quote in `type.code`, and the cited lines with two lines of context when available (M5). Withdrawn rows also show the claim's reason code in words: `no_citations` "No citation given", `source_missing` "Cited source does not exist", `line_out_of_range` "Cited lines are outside the source", `quote_not_found` "Quote is not in the cited lines". Each failing citation shows its own reason.
4. **Withdrawn list.** Withdrawn claims stay in the list, in their original order, with a filter "Show: all, verified, withdrawn". Never collapsed by default.
5. **Audit verdict.** From `audit_result.audit`: `verdict` ("Accepted", "Accepted with a warning", "Rejected"), `model`, each `checks[]` item (`criterion`, `passed`, `note`), `warning`.
6. **Before the diagnosis exists.** The panel reads "The diagnosis appears after the evidence check" with the current status, and the feed below carries the run.

Contract coverage: the contract has only `audit_result` and, after the run, `DeliveryPackage.summary` and `deliverables[].content` (typed `Any`). Root cause, category, claims, citations, per-claim and per-citation status, reason codes, `root_cause_claim_ids`, the remediation plan and the diagnosis status are all missing (M1 to M4).

#### 3.2.4 Budget panel

**Purpose.** Cost against the cap in full: spent, reserved, cap, predicted versus real, by level, sub-budgets and stops.

| Component | Data |
|---|---|
| Spent as the one big numeral (P4), with pills: "Reserved $`held_usd`", "Cap $`cap_usd`", "Predicted $`predicted_usd`" | `budget_update` payload; first values from `RunView` |
| Meter (same rules as the header) | same |
| Predicted versus real: two bars and the difference. After the run, the prediction error from `CostReport.prediction_error` ("real 9.7 percent above predicted"). During the run, a caption: "Predicted is the sum of the estimates made before each call so far, not an estimate made before the run." | `budget_update.predicted_usd`, `.spent_usd`; `DeliveryPackage.cost_report` |
| By level: director, managers, operators, auditor, spent each | `budget_update.spent_by_level`; predicted per level is missing (M12) |
| Sub-budgets: per agent, allocated, released, and what is free in its parent | `budget_allocation` (`action`, `agent_id`, `parent_agent_id`, `usd`, `parent_free_usd`) |
| Stops: one row per stopped scope | `budget_exhausted` (`agent_id`, `level`, `scope`, `key`, `cap_usd`, `committed_usd`, `requested_usd`); `LedgerView.stops` |
| Estimated usage: "2 charges were estimated (no usage returned)" | `LedgerView.usage_estimated_entries`; `budget_update.entry.usage_estimated`; `CostReport.usage_estimated_entries` |
| Ledger table (collapsed by default): one row per entry with level, task, model, tokens in, cached, out, real and predicted | `LedgerView.entries[]`, `budget_update.entry` (`level`, `task_id`, `model`, `input_tokens`, `cached_tokens`, `output_tokens`, `usd_real`, `usd_predicted`, `cached_price_fallback`, `usage_estimated`) |

Money is shown with all six decimals everywhere ("$0.015903"), in mono with tabular figures, so a display never rounds spend under a cap it passed. The panel title says "Budget (USD)" once. Before the first `budget_update`, values read "Not started", never "$0.000000".

#### 3.2.5 Team (org chart)

**Purpose.** Who is working, on what, and where the money and failures went.

- An indented tree (director, then auditor and managers, then each manager's operators), not a free-form graph, so it reads on a phone and with a screen reader (`role="tree"`).
- Node: role, `level` label, `model` (short name), status chip (Hired, Working, Idle, Done, Failed), allocation and spent.
- Data: `agent_hired` (`AgentNode`: `agent_id`, `level`, `role`, `model`, `operator_id`, `parent_id`, `skills`, `tools`, `status`); `GET /org` snapshot. Working and done are derived from `task_started` and `task_result` for operators. Status changes for other levels are not events (M11). Spent per agent maps through `task_id` (`task_assigned.agent_id`) for operators only, because `LedgerEntry` has no `agent_id` (M10).
- Reassignments: an arrow from the failed operator to the new one, from `escalation` (`from_agent_id`, `to_agent_id`, `task_id`, `reason`); escalations to the director likewise.
- A task under its operator shows its attempts ("first pass", "retry", "escalation", from `AttemptRecord.reason` and the task `label`) and its validation errors on demand (`attempt_recorded.attempt.validation_errors`, `TaskView.attempts`).

#### 3.2.6 Live feed

**Purpose.** What is happening now, in order.

- One row per event: time since `run_started` (mono), actor (agent role, resolved through `agent_hired`), a sentence, and a detail toggle.
- Sentences per `type`: `agent_hired` "Manager joined (nemotron-3-super)"; `task_assigned` "Task t-1 to log-reader (slice of `app.log`)"; `task_started` "Attempt 2 on nemotron-3-super"; `attempt_recorded` "Attempt failed validation (1 error)"; `tool_called` "Searched (ok)"; `budget_update` "Charged $0.004800 (director, plan)"; `budget_allocation` "Held $0.015000 for Manager 1" or "Released $0.002826 back to Manager 1"; `budget_exhausted` "Operator stopped: allocation used up"; `message` "Director wrote" (text in the chat); `task_result` "Task t-1 done, first pass"; `escalation` the `reason`; `audit_result` "Auditor: accepted"; `run_finished`, `run_failed` and `mode_notice` as their own banner rows.
- Filter chips: All, Team, Tasks, Budget, Messages, Audit. Budget events are the noisiest and can be hidden.
- "Following" mode keeps the newest row in view; scrolling up pauses it and shows "12 new events" to jump back.
- Connection line under the feed: "Connected", "Reconnecting (last event 41)" while the `EventSource` retries with `Last-Event-ID`, "Run ended" after the terminal event.
- `tool_called.args` is never shown (it is null outside debug).

#### 3.2.7 Chat with the director

- Thread of `ChatMessage` (`sender`, `text`, `ts`) from `GET /messages` and `message` events. Only the director talks (communication is vertical); user messages are right-aligned.
- Input: `POST /runs/{run_id}/messages` (`PostMessageRequest.text`, 1 to 4000 characters); the reply arrives as a `message` event. Disabled in recorded runs with "Recorded run: you can read the chat but not write in it" (409 `recorded_run`), and after the run ends (409 `run_not_active`).
- Note from docs/api.md, "Not in core yet": user messages are not built in core; until they are, the input is hidden in live runs too, with the note "Questions to the director are not built yet".

### 3.3 (c) Recorded-mode banner

**Purpose.** A recording must never pass for a live run (docs/api.md, "Modes").

- Full width, above the run header, on every screen of a recorded run, not dismissible, `color.info-tint` with a `color.info` left rule.
- Text: "RECORDED RUN" (`type.label`), then the `mode_notice.detail` text when the stream has sent it (`notice: "recorded_mode"`), otherwise the fixed line "Replaying a saved run with its original timing. It costs nothing and cannot be changed."
- Facts on the right: "Synthetic incident" when `simulated_case` is true; "Cost when recorded: $`spent_usd`" (`RecordingSummary.spent_usd`); the recording date is missing (M15).
- Action: "Start a live run" when live is available in `ModesView`; otherwise nothing.
- Triggers: `RunView.mode == "recorded"`, any event with envelope `mode: "recorded"`, any run-scoped view with `mode: "recorded"`. The mode chip in the header also reads "Recorded".
- A replay cannot be sped up or skipped from the client today (M16).

### 3.4 (d) States

#### 3.4.1 Loading

- Landing: the hero renders without data; the limits row and the recorded run cards show fixed-size skeletons until `GET /modes` answers. Buttons stay disabled with "Checking what is available" until then. If `/modes` fails: "Could not reach the Rookwise API. Try again." and a retry button.
- Run view, before `run_started`: "Connecting to the run" in the header; panels at their final size with skeletons, so nothing jumps when data arrives. Money shows "Not started", never zero.
- Reconnecting: the header keeps the last known values, the connection line reads "Reconnecting (last event N)", and the meter is outlined as stale (dashed border-strong) until a new event or a snapshot arrives. 204 on reconnect means the run is over: show the final state.
- Skeletons do not shimmer under reduced motion.

#### 3.4.2 Live run refused (429, one live run per visitor per day)

Triggers: `POST /runs` with `mode: "live"` answers 429 `ErrorResponse` with `code: "live_refused"` and `details.refusal` `visitor_limit_reached` or `daily_cap_reached`, plus a `Retry-After` header in seconds. Also after creation: `mode_notice` with `notice: "live_refused"`, then `run_failed` with `code: "live_refused"` and `spent_usd: "0.000000"`.

- `visitor_limit_reached`: headline "You have used today's live run." Body: "Each visitor gets 1 live run per day. Nothing was spent. You can try again after 02:00 your time, or watch a recorded run now."
- `daily_cap_reached`: headline "Today's live budget is used up." Body: "Live runs share a daily cap of $`max_usd_per_day` across all visitors. Nothing was spent."
- Buttons: "Watch a recorded run" (primary; an explicit new `POST /runs` with `mode: "recorded"`) and "Back". The page never switches to a recording on its own (D3).
- The reset time comes from `Retry-After`. Cross-origin, the browser can read that header only if the server sends `Access-Control-Expose-Headers: Retry-After`; otherwise the copy drops the time (M14).
- Related refusals, same layout: 503 `live_disabled` ("Live runs are off on this deployment"); 422 `run_cap_exceeded` stays inline on the cap field.
- `ErrorResponse.error.request_id` is shown in small mono text ("Reference req-1") for support.

#### 3.4.3 Inconclusive diagnosis

Today's signal: `audit_result.audit.verdict == "rejected"`, a failed check "The diagnosis rests on supported claims" and a `warning` that starts with "Inconclusive" (docs/ARCHITECTURE.md, "The evidence rule"). Detecting it means matching a string; a typed status is missing (M3).

- The diagnosis header reads "Inconclusive: no root cause is backed by the evidence." in `color.danger`, with the line "Every claim the root cause rested on was withdrawn. The auditor made no model call."
- The withdrawn claims are listed first, each with its reason (3.2.3), so the user sees exactly what failed.
- The remediation gate is not shown. No "approve" control exists for an inconclusive result.
- The budget panel shows what the run spent; the copy does not suggest that a larger cap would have helped (no data backs that).
- Unread slices and empty sources would explain gaps but are not in the contract (M13).

#### 3.4.4 Budget stop

Triggers: `budget_exhausted` (any level). What follows depends on the level (docs/api.md, `budget_exhausted`): director, `run_failed` with `code: "budget_exhausted"`; manager, `run_finished` with `partial: true`; operator, the task fails and is not reassigned; auditor, accepted with a warning that only the deterministic check ran.

- A `color.danger-tint` banner at the top of the main column: "Stopped at the cap. Spent $0.100000 of $0.100000. The result below is partial." For an operator or manager stop: "Manager 2 stopped on its budget: it needed $0.005100 and had $0.003000 left. Its block is partial." Values: `requested_usd`, and `cap_usd` minus `committed_usd` computed in integer micro-USD.
- The meter turns `color.danger`; the stopped agent in the org chart gets a "Stopped: budget" chip; the stop is a row in the budget panel.
- Every partial deliverable carries a "Partial" chip. Partial is never presented as complete.
- If spent passed the cap through an under-reserved call, the banner says so with the amount over.

#### 3.4.5 Other terminal states (short)

- Cancelled: `run_finished` with `status: "cancelled"`, `partial: true`: "You cancelled the run. Spent $X. Calls cut off were charged as estimated."
- Failed: `run_failed` with `plan_failed` or `plan_too_large`: the `error.message`, the spend, and "Nothing after the plan ran."

### 3.5 Fields the contract does not have

Flagged only; docs/api.md is not changed here.

| # | Needed by | Missing |
|---|---|---|
| M1 | Evidence view, remediation gate | The diagnosis: `root_cause`, `category`, `claims[]` (`claim_id`, `text`, `citations[]` with `source_id`, `line_start`, `line_end`, `quote`), `root_cause_claim_ids`, `remediation_plan[]` (`action`, `why`, `risk`, `reversible`). Today only `DeliveryPackage.summary` and the untyped `Deliverable.content`. |
| M2 | Evidence view | The evidence check per claim and per citation: supported or withdrawn, the claim reason code, each citation's reason, and the counts (supported, withdrawn, withdrawn per reason). The operators' check (`operator_evidence`) too. |
| M3 | Inconclusive state | A typed diagnosis status (`audited` or `inconclusive`) and its reason. Today an inconclusive result is `verdict: "rejected"` plus a warning string that starts with "Inconclusive". |
| M4 | Evidence view during a run | An event that carries the diagnosis and the evidence check when they exist, before `run_finished`; the package answers 409 `package_not_ready` until the end. |
| M5 | Evidence view | The cited lines with surrounding context (or an endpoint that serves line ranges of a run's sources). With M1 alone the UI has the quote but not the lines around it. |
| M6 | Remediation gate | Approval of the remediation plan: a status, an endpoint and an event (docs/ARCHITECTURE.md, "The human approval gate", says this needs a contract change). |
| M7 | Plan gate | A structured plan for approval: blocks, tasks, the source each task reads, and a predicted cost for the plan. Today the plan is the director's prose `message`, and no cost is predicted before the run (not built in core). |
| M8 | Plan gate in recorded runs, other tabs | An event that records the human decision (`approved`, `note`, time), so a replay shows what was decided and when. |
| M9 | Live intake | Evidence selection in `CreateRunRequest` (for example an incident id) and the list of selectable incidents in `ModesView`. Today live intake is a free-text `goal` and a cap. |
| M10 | Org chart, budget by agent | `agent_id` on `LedgerEntry`. Director, manager and auditor calls are identifiable only by `task_id` strings such as `plan` or `b-1-summary`, which the UI must not parse. |
| M11 | Org chart | Agent status changes as events (working, idle, done, failed). Only `agent_hired` with `status: "hired"` is emitted; other statuses exist only in the `GET /org` snapshot, which core does not build yet. |
| M12 | Budget panel | Predicted cost per level (`predicted_by_level` next to `spent_by_level`). |
| M13 | Inconclusive and partial states | Unread slices and empty sources (`TeamRun.unread_slices`, `TeamRun.empty_sources`). |
| M14 | Refusal state | A reset time the browser can read: `Access-Control-Expose-Headers: Retry-After` on cross-origin responses, or `details.retry_after_s` in the error body. |
| M15 | Landing recordings, recorded banner | On `RecordingSummary`: when it was recorded, and the incident id and category it ran on. |
| M16 | Recorded banner | A replay speed or skip-to-end option for recorded streams (the server paces the replay with the original delays). |

## 4. Content rules

1. **No result numbers on the landing until the benchmark produced them.** Every benchmark cell, accuracy figure, cost comparison and prediction error reads "TBD from benchmark" in a visible placeholder: `type.label` text in `color.muted`, inside a dashed `color.border-strong` box, so it can never be mistaken for a real zero. A placeholder is replaced only by a number copied from a committed benchmark report, with a caption naming the split (dev or test) and the date (P5).
2. **No claim the code cannot back.** Examples:
   - Do not write "the run can never pass the cap". Write "The ledger reserves money before every call and refuses calls that do not fit." (A call whose real usage exceeds its reservation can pass the cap; docs/ARCHITECTURE.md, "Cost of a call".)
   - Do not write "verified root cause". Write "claims verified against the cited lines". The check proves the quote is in the cited lines, not that the claim is true.
   - Do not write "remediates", "fixes" or "auto-heals". v1 executes nothing.
   - Do not call the prediction an estimate of the run made up front. It is the sum of per-call predictions (docs/ARCHITECTURE.md, "What a run reports").
   - Do not claim a speed or duration; the duration of a real run is not measured.
   - Do not show customer logos, testimonials, user counts or "trusted by".
3. **Synthetic stays labelled.** Text that arrives with "[synthetic]" is shown as is, and a synthetic run carries the "Synthetic incident" chip on every screen.
4. **Recorded stays labelled** (3.3), on every screen of a recorded run.
5. **Money:** six decimals, "$" with "USD" named once per panel, mono with tabular figures, never rounded in a way that changes a comparison with the cap.
6. **Unverified stays unverified.** Anything docs/ARCHITECTURE.md marks UNVERIFIED (for example reasoning-token billing) is not stated as fact in the UI.
7. **No secrets in the UI.** The web app never receives or shows keys, prompts or model internals (docs/api.md, "What the UI never receives").

## 5. Responsive behavior and accessibility

### 5.1 Phone width (360 to 430 px)

- One column, 16 px gutters, no horizontal page scroll at 320 px either.
- Run view order, same as the DOM: recorded banner (two lines), sticky header reduced to mode chip, status, "Spent $X of $Y" and the meter, plus the "Decision needed" chip when relevant; then the approval gate, diagnosis and evidence, team, feed, budget panel, chat. The header's jump links become a horizontal row of section chips under the header (the row may scroll on its own; the page does not).
- Log quotes wrap (`white-space: pre-wrap; overflow-wrap: anywhere`) instead of scrolling sideways; the line number stays on its own line above the quote.
- The org chart stays an indented list; indentation is capped at 3 levels of 12 px each.
- The ledger table becomes a list of cards (one per entry).
- Chat becomes a full-height drawer opened from a "Chat" button in the header; the input sits above the on-screen keyboard.
- Landing: headline at `type.display` phone size, hero buttons full width and stacked, step cards stacked, the limits row becomes a 2 by 2 grid.
- Touch targets at least 44 by 44 px (beyond the 24 px AA minimum of WCAG 2.2, 2.5.8).

### 5.2 Keyboard order and focus

- First focusable element: "Skip to the run" (run view) or "Skip to content" (landing).
- Run view tab order: skip link, run header (mode chip info, Decision needed link, jump links, Cancel), approval gate (note, Approve, Reject), evidence filter and claims (each claim row is focusable; Enter expands its citations), team tree (arrow keys move inside the tree, Tab leaves it), feed filters and the "jump to newest" control (the feed list itself is one tab stop), budget panel (the ledger table toggle), chat input and Send.
- Focus ring: 2 px solid `color.focus` with a 2 px offset on every interactive element, never removed; ratios in 2.2.
- Focus is never moved by an incoming event. A new gate, a stop or the end of the run is announced (5.3) and reachable through the header chip.
- Dialogs (live intake, cancel confirmation) trap focus, close on Escape, and return focus to the button that opened them. The Cancel confirmation's default focus is "Keep running".

### 5.3 Screen readers

- Landmarks: `header`, `main`, `aside` (side column), `nav` (jump links).
- One polite live region announces only: decision needed, budget at 80 percent of the cap, budget stop, audit result, run finished or failed, live refusal, reconnecting and reconnected.
- The feed is `role="log"` with `aria-live="off"`, so dozens of budget events per minute are not read aloud; a toggle "Announce feed events" turns it to polite.
- The meter is `role="meter"` with `aria-valuetext` such as "Spent $0.015903 of $0.100000 cap, $0.004000 reserved".
- Status chips expose their words; icons are `aria-hidden`.
- Money is read correctly: the visible "$0.015903" has no extra markup that splits it.

### 5.4 Reduced motion and other preferences

- `prefers-reduced-motion: reduce`: no meter width transitions, no skeleton shimmer, no live-dot pulse, no drawer slide (opacity only, at most 120 ms). Feed auto-follow still works; it jumps instead of scrolling smoothly.
- `prefers-contrast: more`: `color.border` takes the value of `color.border-strong`, and tints get a 1 px border in their status color.
- `forced-colors: active`: status chips keep their words and icons; the meter keeps a visible outline using system colors.
- Text zoom to 200 percent and reflow at 320 CSS px must not lose content or functionality.

## 6. Open questions for the user

1. **Theme default.** Follow the system setting with dark as the fallback (proposed), or dark only?
2. **Fonts.** Self-host the OFL fonts in `web/` (no third-party request; the license files ship with them) or load them from a font CDN?
3. **Brand.** There is no logo or mark. Use a text wordmark only for the hackathon, or should a mark be designed? And may the landing name Nebius, NVIDIA and Tavily in text only (proposed), or should their logos appear under their brand rules?
4. **Contract changes.** Which of M1 to M16 go into the contract before `web/` is built? M1 to M4 and M6 block the evidence view and the remediation gate; M9 blocks a meaningful live intake.
5. **Live intake.** What can a visitor investigate live: only the corpus incidents (and which split), or a free-text goal? Real logs from visitors seem out of scope for v1.
6. **Default live cap.** What `budget_usd` should the live intake prefill: the hierarchy's per-incident cap (USD 0.10, D2, unmeasured) or something else, below `LIVE_DEMO_MAX_USD_PER_RUN`?
7. **Plan approval in the demo.** Should a visitor approve the plan in a live run (status `awaiting_approval`), or does the live demo skip plan approval and keep only the remediation gate? Core does not wait for approval yet.
8. **Money display.** Six decimals everywhere (proposed, so nothing is rounded under the cap), or fewer decimals in the header with six in the panel?
9. **Replay control.** Should recorded runs offer a faster replay or skip to the end (M16), or always play at the original timing?
10. **Proof domains on the landing.** One line mentioning SOC triage and smart-contract review as generality proofs, or leave them to the README and the video?
11. **Run excerpt in the hero.** Show a static excerpt of the chosen recorded run (proposed), or leave the hero without a visual until the recorded demo is chosen?
