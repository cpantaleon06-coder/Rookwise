import { useCallback, useEffect, useState } from "react";
import { runHref } from "../App";
import { LiveRunsControl, REPO_URL, SiteFooter, SkipLink, ThemeToggle } from "../components/chrome";
import { buttonClass, Chip, Label, Placeholder, Skeleton, Usd } from "../components/ui";
import { splitOf, SPLIT_CHIP } from "../lib/incidents";
import { formatDate, reasonWords } from "../lib/labels";
import {
  loadIndex,
  RecordingError,
  type ClaimExcerpt,
  type IndexEntry,
  type RunExcerpt,
} from "../lib/recording";

const BASE = `${import.meta.env.BASE_URL}recordings/`;

type IndexState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; recordings: IndexEntry[] };

function useRecordingIndex() {
  const [state, setState] = useState<IndexState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    loadIndex(BASE, (url) => fetch(url))
      .then((index) => !cancelled && setState({ kind: "ready", recordings: index.recordings }))
      .catch((error: unknown) => {
        if (cancelled) return;
        const message =
          error instanceof RecordingError ? error.message : "The list of recordings could not be loaded.";
        setState({ kind: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);
  const retry = useCallback(() => {
    setState({ kind: "loading" });
    setAttempt((n) => n + 1);
  }, []);
  return { state, retry };
}

function SiteHeader() {
  const [open, setOpen] = useState(false);
  const links = (
    <>
      <a className="label inline-flex min-h-11 items-center px-3 text-muted hover:text-ink" href="#how-it-works">
        How it works
      </a>
      <a className="label inline-flex min-h-11 items-center px-3 text-muted hover:text-ink" href={REPO_URL} rel="noreferrer">
        Source on GitHub
      </a>
    </>
  );
  return (
    <header className="border-b border-line">
      <div className="mx-auto flex max-w-[1440px] items-center justify-between gap-2 px-4 py-2 sm:px-6 lg:px-8">
        <a href="#/" className="text-lg font-semibold tracking-tight">
          Rookwise
        </a>
        <nav aria-label="Site" className="hidden items-center sm:flex">
          {links}
          <ThemeToggle />
        </nav>
        <button
          type="button"
          className="label inline-flex min-h-11 items-center rounded-full border border-line-strong px-4 sm:hidden"
          aria-expanded={open}
          aria-controls="site-menu"
          onClick={() => setOpen((v) => !v)}
        >
          Menu
        </button>
      </div>
      {open && (
        <nav id="site-menu" aria-label="Site" className="flex flex-col border-t border-line px-4 py-2 sm:hidden">
          {links}
          <ThemeToggle />
        </nav>
      )}
    </header>
  );
}

function provenanceChip(entry: IndexEntry) {
  if (entry.provenance === "real_model_output") {
    return <Chip tone="info">Real model output</Chip>;
  }
  if (entry.provenance === "synthetic_fixture") {
    return <Chip tone="info">Synthetic fixture, not model output</Chip>;
  }
  return null;
}

function ExcerptClaim({ claim, verified }: { claim: ClaimExcerpt; verified: boolean }) {
  return (
    <div className={`rounded-[10px] border border-line p-4 ${verified ? "" : "bg-danger-tint"}`}>
      <div className="mb-2">
        {verified ? (
          <Chip tone="ok">Verified</Chip>
        ) : (
          <Chip tone="danger">Withdrawn: {reasonWords(String(claim.reason))}</Chip>
        )}
      </div>
      <p className="text-sm/5">{claim.text}</p>
      {claim.citation && (
        <div className="mt-3 rounded-[6px] bg-raised p-3">
          <Label>
            {claim.citation.source_id} L{claim.citation.line_start}
            {claim.citation.line_end !== claim.citation.line_start ? ` to L${claim.citation.line_end}` : ""}
          </Label>
          <p className="quote mt-1 line-clamp-4">{claim.citation.quote}</p>
        </div>
      )}
    </div>
  );
}

function HeroExcerpt({ entry }: { entry: IndexEntry | null }) {
  const excerpt: RunExcerpt | null = entry?.excerpt ?? null;
  if (!entry || !excerpt) {
    return (
      <div className="placeholder-box flex min-h-64 items-center justify-center p-6 text-center">
        <span className="label">Run excerpt: TBD from the recorded demo</span>
      </div>
    );
  }
  return (
    <figure className="flex flex-col gap-3 rounded-[16px] border border-line bg-surface p-4 sm:p-6">
      <figcaption className="text-sm text-muted">
        From the recording “{entry.summary.title}”. Claims checked by code against the cited lines.
      </figcaption>
      {excerpt.verified && <ExcerptClaim claim={excerpt.verified} verified />}
      {excerpt.withdrawn && <ExcerptClaim claim={excerpt.withdrawn} verified={false} />}
    </figure>
  );
}

function RecordingCard({ entry }: { entry: IndexEntry }) {
  const s = entry.summary;
  const recorded = formatDate(s.recorded_at);
  const split = splitOf(s.incident_id);
  return (
    <li className="flex min-w-0 flex-col gap-3 rounded-[10px] border border-line bg-surface p-4 sm:p-6">
      <div className="flex flex-wrap gap-2">
        {provenanceChip(entry)}
        {s.simulated_case && <Chip tone="neutral">Synthetic incident</Chip>}
        {split && <Chip tone="neutral">{SPLIT_CHIP[split]}</Chip>}
      </div>
      <h3 className="wrap-anywhere text-xl/7 font-semibold">{s.title}</h3>
      <p className="wrap-anywhere text-sm text-muted">{s.goal}</p>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div className="min-w-0">
          <dt><Label>Cost when recorded</Label></dt>
          <dd><Usd value={s.spent_usd} /></dd>
        </div>
        {entry.capUsd && (
          <div className="min-w-0">
            <dt><Label>Cap</Label></dt>
            <dd><Usd value={entry.capUsd} /></dd>
          </div>
        )}
        {recorded && (
          <div className="min-w-0">
            <dt><Label>Recorded</Label></dt>
            <dd className="num">{recorded}</dd>
          </div>
        )}
        {s.incident_id && (
          <div className="min-w-0">
            <dt><Label>Incident</Label></dt>
            <dd className="num wrap-anywhere">{s.incident_id}</dd>
          </div>
        )}
        {s.category && (
          <div className="col-span-2 min-w-0">
            <dt><Label>Incident category (corpus)</Label></dt>
            <dd className="num wrap-anywhere">{s.category}</dd>
          </div>
        )}
      </dl>
      <div className="mt-auto pt-2">
        <a className={buttonClass("primary")} href={runHref(entry.folder)}>
          Watch<span className="sr-only">: {s.title}</span>
        </a>
      </div>
    </li>
  );
}

const STEPS = [
  ["You pick the evidence and set a cap", "The cap is in USD and is set before the run starts."],
  ["Cheap models read the logs in slices", "Each operator reads one slice and cites the lines it relies on."],
  ["A strong model writes the diagnosis", "The director turns the findings into a root cause and a remediation plan."],
  ["Code checks every citation", "Unsupported claims are withdrawn and stay listed with their reason."],
  ["An auditor reviews, and you decide", "Approving records your decision. v1 executes nothing."],
] as const;

const CHECKS = [
  [
    "Every claim cites a line",
    "Source, line numbers and the quote. A deterministic check (core/evidence.py, no model) confirms the quote is in the cited lines.",
  ],
  [
    "A budget set before the run",
    "The ledger reserves money before each call and refuses calls that do not fit. Predicted versus real is reported.",
  ],
  ["You decide", "Approving records the decision and runs nothing on your systems."],
] as const;

export function Landing() {
  const { state, retry } = useRecordingIndex();
  const recordings = state.kind === "ready" ? state.recordings : [];
  const first = recordings[0] ?? null;

  return (
    <>
      <SkipLink target="content">Skip to content</SkipLink>
      <SiteHeader />
      <main id="content" className="mx-auto max-w-[1440px] px-4 sm:px-6 lg:px-8">
        {/* Hero (P6) */}
        <section className="grid gap-10 py-16 lg:grid-cols-2 lg:items-center lg:py-24">
          <div className="min-w-0">
            <h1 className="font-serif text-[2.5rem]/[2.75rem] font-medium sm:text-[3.5rem]/[3.75rem]">
              Incident answers
              <br />
              <span className="text-muted">you can check line by line.</span>
            </h1>
            <p className="mt-6 max-w-[60ch] text-muted">
              Rookwise is a team of AI agents that investigates an incident under a budget you set
              before the run. Every claim cites the log lines it rests on, and code checks each
              citation. This site replays recorded runs; replaying costs nothing.
            </p>
            <div className="mt-8 flex flex-col gap-4 sm:flex-row sm:items-start">
              {state.kind === "loading" && (
                <button type="button" disabled className={`${buttonClass("primary")} w-full sm:w-auto`}>
                  Checking what is available
                </button>
              )}
              {state.kind === "ready" && first && (
                <a href={runHref(first.folder)} className={`${buttonClass("primary")} w-full sm:w-auto`}>
                  Watch a recorded run
                </a>
              )}
              {state.kind === "ready" && !first && (
                <p className="text-muted">No recorded run is published yet.</p>
              )}
              {state.kind === "error" && (
                <div role="alert" className="flex flex-col gap-2">
                  <p>Could not load the recordings. {state.message}</p>
                  <button type="button" onClick={retry} className={buttonClass("secondary")}>
                    Try again
                  </button>
                </div>
              )}
              <LiveRunsControl />
            </div>
          </div>
          <div className="min-w-0">
            {state.kind === "loading" ? <Skeleton className="h-64 w-full" /> : <HeroExcerpt entry={first} />}
          </div>
        </section>

        {/* Recorded runs */}
        <section aria-labelledby="recordings-title" className="border-t border-line py-16 sm:py-24">
          <Label>Recorded runs</Label>
          <h2 id="recordings-title" className="mt-3 text-2xl/8 font-semibold">
            Watch a saved run with its original timing.
            <span className="text-muted"> Speed it up or jump to the end.</span>
          </h2>
          <div className="mt-8">
            {state.kind === "loading" && (
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                <Skeleton className="h-72" />
                <Skeleton className="h-72" />
              </div>
            )}
            {state.kind === "error" && <p className="text-muted">The recordings could not be listed.</p>}
            {state.kind === "ready" && recordings.length === 0 && (
              <p className="text-muted">No recorded run is published yet.</p>
            )}
            {state.kind === "ready" && recordings.length > 0 && (
              <ul className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {recordings.map((entry) => (
                  <RecordingCard key={entry.folder} entry={entry} />
                ))}
              </ul>
            )}
          </div>
        </section>

        {/* How it works (P10) */}
        <section id="how-it-works" aria-labelledby="how-title" className="scroll-mt-4 border-t border-line py-16 sm:py-24">
          <Label>How it works</Label>
          <h2 id="how-title" className="mt-3 text-2xl/8 font-semibold">
            Five steps from evidence to decision.
          </h2>
          <ol className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            {STEPS.map(([title, line], i) => (
              <li key={title} className="rounded-[10px] border border-line bg-surface p-4">
                <span className="num text-muted">{String(i + 1).padStart(2, "0")}</span>
                <h3 className="mt-2 font-semibold">{title}</h3>
                <p className="mt-1 text-sm text-muted">{line}</p>
              </li>
            ))}
          </ol>
        </section>

        {/* What you can check (P9) */}
        <section aria-labelledby="check-title" className="border-t border-line py-16 sm:py-24">
          <Label>What you can check</Label>
          <h2 id="check-title" className="mt-3 text-2xl/8 font-semibold">
            Nothing to take on trust.
            <span className="text-muted"> Each promise is visible in the run view.</span>
          </h2>
          <div className="mt-8 grid gap-4 md:grid-cols-3">
            {CHECKS.map(([title, line]) => (
              <div key={title} className="rounded-[10px] border border-line bg-surface p-6">
                <h3 className="text-xl/7 font-semibold">{title}</h3>
                <p className="mt-2 text-sm text-muted">{line}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Benchmark (section 4 rule 1) */}
        <section aria-labelledby="bench-title" className="border-t border-line py-16 sm:py-24">
          <Label>Benchmark</Label>
          <h2 id="bench-title" className="mt-3 text-2xl/8 font-semibold">
            Hierarchy against one large and one small model.
          </h2>
          <div className="mt-8 flex flex-col gap-3 md:hidden">
            {["(a) Hierarchy", "(b) Single large model", "(c) Single small model"].map((name) => (
              <div key={name} className="rounded-[10px] border border-line bg-surface p-4">
                <h3 className="font-semibold">{name}</h3>
                <dl className="mt-2 grid gap-2 text-sm">
                  {["Diagnosis correct (test split)", "Real cost", "Predicted versus real"].map((col) => (
                    <div key={col} className="flex flex-wrap items-center justify-between gap-2">
                      <dt className="text-muted">{col}</dt>
                      <dd><Placeholder>TBD from benchmark</Placeholder></dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
          </div>
          <table className="mt-8 hidden w-full border-collapse text-left text-sm md:table">
            <thead>
              <tr className="border-b border-line">
                <th scope="col" className="label py-3 pr-4 text-muted">Configuration</th>
                <th scope="col" className="label py-3 pr-4 text-muted">Diagnosis correct (test split)</th>
                <th scope="col" className="label py-3 pr-4 text-muted">Real cost</th>
                <th scope="col" className="label py-3 text-muted">Predicted versus real</th>
              </tr>
            </thead>
            <tbody>
              {["(a) Hierarchy", "(b) Single large model", "(c) Single small model"].map((name) => (
                <tr key={name} className="border-b border-line">
                  <th scope="row" className="py-3 pr-4 font-medium">{name}</th>
                  <td className="py-3 pr-4"><Placeholder>TBD from benchmark</Placeholder></td>
                  <td className="py-3 pr-4"><Placeholder>TBD from benchmark</Placeholder></td>
                  <td className="py-3"><Placeholder>TBD from benchmark</Placeholder></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-4 text-sm text-muted">
            6 synthetic incidents, 3 dev and 3 test. Test results are reported apart from dev. Numbers
            appear here only once a committed benchmark report has them.
          </p>
        </section>

        {/* Limits */}
        <section aria-labelledby="limits-title" className="border-t border-line py-16 sm:py-24">
          <Label>Limits</Label>
          <h2 id="limits-title" className="mt-3 text-2xl/8 font-semibold">What this is not.</h2>
          <ul className="mt-6 list-disc space-y-2 pl-5 text-muted">
            <li>The incidents are synthetic: generated logs, metrics and diffs, not a real outage.</li>
            <li>v1 executes nothing. Approving a recommendation only records your decision.</li>
            <li>This site replays recordings. It starts no run and calls no model.</li>
            <li>A citation check proves the quote is in the cited lines, not that the claim is true.</li>
            <li>Benchmark numbers appear only once they are measured and committed.</li>
          </ul>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
