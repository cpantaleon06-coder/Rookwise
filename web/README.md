# Rookwise web: recorded run replay

A static web app that replays a recorded Rookwise run in the browser: the budget ledger, the org chart, the tasks, the evidence check, the audit and the cost report, predicted versus real. It has no backend and no live mode. The only requests it makes are for its own files, including the recording JSON under `recordings/`.

Design: [DESIGN.md](DESIGN.md). Contract: [docs/api.md](../docs/api.md).

## Run it

Node 20 or newer.

```bash
cd web
npm install
npm run dev
```

Open the URL Vite prints (http://localhost:5173 by default).

Other scripts:

| Command | What it does |
|---|---|
| `npm test` | Vitest: replay logic, money formatting, run state, recording loader, approval store |
| `npm run lint` | ESLint |
| `npm run build` | Type-check, then build to `dist/` |
| `npm run preview` | Serve `dist/` locally |

## Recordings

A recording is a folder under `public/recordings/` with two files:

- `recorded_run.json`: the bundle (sections `run`, `org`, `ledger`, `messages`, `tasks`, `package`, and either `modes` for the synthetic fixture or `recording` for an exported real run).
- `recorded_run.events.json`: `{"run_id", "events": [{"delay_ms", "event"}]}`.

`public/recordings/` holds two real recorded runs, `inc-03-run2` and `inc-01-run3` (real model output on synthetic dev incidents, copied from `examples/api/recordings/`); the landing opens the newest real one by default. The synthetic fixture from `examples/api/` (not model output; it says so) lives in `test-fixtures/recordings/demo/` and is used by the tests only, so the build does not publish it. To add a recording, add a folder with those two files. The build lists every such folder in `recordings/index.json` (a Vite plugin in `vite.config.ts` writes it; the dev server serves it live), real model output first, then the newest. A recording opens at `#/run/<folder>`. Folder names use letters, digits, dots, dashes and underscores.

How the replay reads a recording:

- Events are sorted by `seq` and deduplicated by `id`. Each waits its `delay_ms`, capped at 1.5 s. Speeds: 1x, 4x (a quarter of each capped wait), and instant.
- Money stays the six-decimal strings from the files. When the app adds or compares amounts, it parses them into integer micro-USD (`BigInt`), never JavaScript floats, and formats them for display with all six decimals.
- The diagnosis, evidence check, audit, coverage, cost report and delivery package are shown once the replay reaches the end of the run, so a replay does not reveal the result early.
- Optional fields from the 2026-10-25 contract change (`diagnosis`, `evidence_check`, `diagnosis_status`, `coverage` on the package; `recorded_at`, `incident_id`, `category` on the recording summary) are rendered when present. A block whose field is absent is hidden; a field that is present but `null` reads "Not recorded", never an empty list. A `null` package counts as no package.

## The approval gate

After the replay ends, the run view offers "Approve recommendation" and "Reject". The choice is kept in this tab's memory only (no storage, no request) and is gone after a reload. Rookwise v1 executes nothing either way.

## Deploy on Vercel

1. Import the repository in Vercel.
2. Set **Root Directory** to `web`.
3. Framework preset: **Vite**. Build command: `npm run build`. Output directory: `dist`.
4. No environment variables are needed.

`vercel.json` repeats the preset, build command and output directory, and sets security headers, including a Content Security Policy that only allows the app's own origin. The app uses hash routes (`#/run/inc-03-run2`), so no rewrites are needed, and it builds with a relative base, so any static host works.

## Privacy

No auth, no analytics, no tracking, no cookies. Fonts (Inter, JetBrains Mono, Source Serif 4, SIL Open Font License 1.1) are bundled from `@fontsource` packages and served by the app itself; their license texts are in `public/licenses/`. The theme choice (system, dark or light) is the only thing kept in `localStorage`.
