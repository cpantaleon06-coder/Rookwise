import { useCallback, useEffect, useState, type ReactNode } from "react";
import { runHref } from "../App";
import { SiteFooter, SiteHeader, SkipLink } from "../components/chrome";
import { DotRook, ProgressRing } from "../components/figures";
import { buttonClass, Skeleton, Stamp } from "../components/ui";
import { runFacts, type RunFacts } from "../lib/facts";
import { LEVEL_WORDS, reasonWords } from "../lib/labels";
import { formatUsd } from "../lib/money";
import {
  BUNDLE_FILE,
  loadIndex,
  RecordingError,
  validateBundle,
  type ClaimExcerpt,
  type IndexEntry,
} from "../lib/recording";
import { teamOf, type TeamSummary } from "../lib/team";

const BASE = `${import.meta.env.BASE_URL}recordings/`;

/** The recording Figure 1 and Table 1 come from. */
const FEATURED = "inc-03-run2";

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

interface Featured {
  facts: RunFacts;
  team: TeamSummary | null;
}

/** The featured recording's facts and team, read from its bundle. Null until loaded or when missing. */
function useFeatured(folder: string | null): Featured | null {
  const [loaded, setLoaded] = useState<{ folder: string; data: Featured | null } | null>(null);
  useEffect(() => {
    if (!folder) return;
    let cancelled = false;
    fetch(`${BASE}${encodeURIComponent(folder)}/${BUNDLE_FILE}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
      .then((data: unknown) => {
        const bundle = validateBundle(data);
        if (!cancelled) setLoaded({ folder, data: { facts: runFacts(bundle), team: teamOf(bundle.org?.nodes) } });
      })
      .catch(() => !cancelled && setLoaded({ folder, data: null }));
    return () => {
      cancelled = true;
    };
  }, [folder]);
  return loaded && loaded.folder === folder ? loaded.data : null;
}

function recordingPath(folder: string): string {
  return `web/public/recordings/${folder}/${BUNDLE_FILE}`;
}

/** A numbered section of the report: a hairline, the number in muted figures, a serif heading. */
function Section({ id, n, title, children }: { id: string; n: string; title: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="mt-89 scroll-mt-21 border-t border-rule pt-34">
      <h2 id={`${id}-title`} className="text-title">
        <span className="figure mr-13 text-muted">{n}</span>
        {title}
      </h2>
      {children}
    </section>
  );
}

/** A caption under a figure or table: "Figure 1." in small caps, then the text and its source. */
function Caption({ label, children, source }: { label: string; children: ReactNode; source: ReactNode }) {
  return (
    <figcaption className="caption mt-13">
      <span className="label mr-8 text-fg">{label}</span>
      {children}
      <span className="mt-8 block">
        <span className="label mr-8">Source</span>
        <span className="num wrap-anywhere">{source}</span>
      </span>
    </figcaption>
  );
}

function StatusMarks() {
  return (
    <p className="ui flex flex-wrap justify-center gap-8">
      <span className="label inline-flex items-baseline gap-8 rounded-full bg-auditor-tint px-13 text-auditor">
        <span aria-hidden="true">○</span>Recorded run, not live
      </span>
      <span className="label inline-flex items-baseline gap-8 rounded-full border border-rule-strong px-13 text-fg">
        <span aria-hidden="true">■</span>Executes nothing
      </span>
    </p>
  );
}

/* Figure 1: one verified and one withdrawn claim ------------------------- */

function lineRange(c: NonNullable<ClaimExcerpt["citation"]>): string {
  return c.line_end !== c.line_start ? `L${c.line_start} to L${c.line_end}` : `L${c.line_start}`;
}

function CitedLine({ claim, verified }: { claim: ClaimExcerpt; verified: boolean }) {
  const c = claim.citation;
  if (!c) return null;
  return (
    <div
      className={`mt-13 border-l-2 py-8 pl-13 ${verified ? "border-supported bg-supported-tint" : "border-withdrawn bg-withdrawn-tint"}`}
    >
      <p className="num text-muted wrap-anywhere">
        {c.source_id} {lineRange(c)}
      </p>
      <p className="quote">{c.quote}</p>
    </div>
  );
}

function ClaimFigure({ entry, facts }: { entry: IndexEntry | null; facts: RunFacts | null }) {
  const excerpt = entry?.excerpt;
  if (!entry || !excerpt?.verified || !excerpt.withdrawn) return null;
  const { verified, withdrawn } = excerpt;
  const wc = withdrawn.citation;
  return (
    <figure className="mt-34 border-b border-rule pb-21">
      <ol className="flex flex-col gap-34">
        <li>
          <Stamp kind="verified" />
          <p className="mt-8">{verified.text}</p>
          <CitedLine claim={verified} verified />
        </li>
        <li>
          <Stamp kind="withdrawn" />
          <p className="mt-8">
            <span className="struck">{withdrawn.text}</span>
            <sup className="ui ml-8 text-withdrawn">
              <a href="#fig1-note-1" aria-label="Note 1: why this claim was withdrawn">
                1
              </a>
            </sup>
          </p>
          <CitedLine claim={withdrawn} verified={false} />
          <p id="fig1-note-1" className="ui mt-8 text-muted">
            <span className="text-withdrawn">1.</span> Reason code <span className="num text-fg">{String(withdrawn.reason)}</span>:{" "}
            {reasonWords(String(withdrawn.reason)).toLowerCase()}
            {wc ? ` (${wc.source_id} ${lineRange(wc)}).` : "."} The claim stays visible, withdrawn.
          </p>
        </li>
      </ol>
      <Caption label="Figure 1." source={recordingPath(entry.folder)}>
        Two claims from the recording “{entry.summary.title}”, as the evidence check judged them. Code, not a
        model, looked for each quote in the cited lines.
        {facts && facts.withdrawn !== null && facts.claims !== null && (
          <>
            {" "}
            In this run {facts.withdrawn} of {facts.claims} claims were withdrawn
            {facts.slicesRead !== null ? `, ${facts.slicesRead} slices were read` : ""}
            {facts.unreadRanges !== null ? ` with ${facts.unreadRanges} unread line ranges` : ""}
            {facts.spentUsd && facts.capUsd ? `, and it spent ${formatUsd(facts.spentUsd)} of a ${formatUsd(facts.capUsd)} cap` : ""}.
          </>
        )}
      </Caption>
    </figure>
  );
}

/* 2. Method --------------------------------------------------------------- */

const SAFEGUARDS = [
  [
    "Contact",
    "Every claim is checked by code",
    "A claim stands only if its quote is in the cited lines. Otherwise it is withdrawn, and shown with the reason.",
  ],
  [
    "Control",
    "The budget cannot be exceeded",
    "Money is reserved before each call. A call that does not fit is refused. There is no bill after the fact.",
  ],
  [
    "Sequence",
    "The steps cannot be skipped",
    "Plan, read, consolidate, judge, verify, audit, approve, in that order. If nothing survives verification, no audit runs and the result is inconclusive.",
  ],
  [
    "Warning",
    "Unread evidence is declared",
    "The report lists the slices that were never read and warns when coverage is low.",
  ],
  [
    "Second check",
    "A second reader audits",
    "A separate model, in a separate context, reviews what remains against a fixed rubric.",
  ],
  [
    "Control",
    "A human decides, nothing executes",
    "Rookwise v1 only reads and recommends. It holds no credentials and cannot change your systems.",
  ],
] as const;

/** Each Shingo label in the mark of what it guards; four hues at most on this screen. */
const KIND_PILL: Record<(typeof SAFEGUARDS)[number][0], string> = {
  Contact: "bg-supported-tint text-supported",
  Control: "bg-cost-tint text-cost",
  Sequence: "border border-rule-strong text-fg",
  Warning: "bg-withdrawn-tint text-withdrawn",
  "Second check": "bg-auditor-tint text-auditor",
};

function levelWords(level: TeamSummary["levels"][number]): string {
  return LEVEL_WORDS[level.level] ?? level.level;
}

function TeamTable({ entry, team }: { entry: IndexEntry; team: TeamSummary }) {
  return (
    <figure className="mt-34">
      <div className="overflow-x-auto" role="region" aria-label="Table 1, scrollable" tabIndex={0}>
        <table className="booktabs ui w-full text-left">
          <thead>
            <tr>
              <th scope="col" className="label py-8 pr-21">Role</th>
              <th scope="col" className="label py-8 pr-21 text-right">Agents</th>
              <th scope="col" className="label py-8">Model</th>
            </tr>
          </thead>
          <tbody>
            {team.levels.map((level) => (
              <tr key={level.level} className="border-b border-rule align-top last:border-b-0">
                <th scope="row" className="py-8 pr-21 font-normal">{levelWords(level)}</th>
                <td className="figure py-8 pr-21 text-right">{level.count}</td>
                <td className="py-8">
                  {level.models.map((m) => (
                    <span key={m.model} className="num block wrap-anywhere">
                      {m.model}
                      {level.models.length > 1 ? ` (${m.count})` : ""}
                    </span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Caption label="Table 1." source={`${recordingPath(entry.folder)} (org)`}>
        The team of the recording “{entry.summary.title}”. Cheap models read; a strong model judges; code verifies; a
        human decides.
      </Caption>
    </figure>
  );
}

/* 3. Results -------------------------------------------------------------- */

// The literal strings check_numbers.py looks for ("2 of 3", "0.920", "0.250") live in this data.
const RESULTS = [
  { split: "test", name: "(a) hierarchy", correct: "2 of 3", recall: "0.333", coverage: "0.920", cost: "0.250" },
  { split: "test", name: "(b) single Ultra", correct: "0 of 3", recall: "0.222", coverage: "0.107", cost: "0.386" },
  { split: "test", name: "(c) single Lightning", correct: "1 of 3", recall: "0.222", coverage: "0.705", cost: "0.119" },
  { split: "dev", name: "(a) hierarchy", correct: "3 of 3", recall: "0.556", coverage: "0.880", cost: "0.290" },
  { split: "dev", name: "(b) single Ultra", correct: "1 of 3", recall: "0.111", coverage: "0.218", cost: "0.409" },
  { split: "dev", name: "(c) single Lightning", correct: "1 of 3", recall: "0.167", coverage: "0.706", cost: "0.121" },
] as const;

const SPLITS = [
  ["test", "Test split, not used while tuning"],
  ["dev", "Dev split, used while tuning"],
] as const;

const CAPTION =
  "Synthetic incidents, 3 per configuration, same 0.50 USD cap for every configuration, test split not used while tuning.";

/** Figure 2: mean coverage on the test split as rings, from the same numbers as Table 2. */
function CoverageRings() {
  const test = RESULTS.filter((r) => r.split === "test");
  return (
    <figure className="mt-34">
      <ul className="ui grid grid-cols-3 gap-13 text-center">
        {test.map((r, i) => (
          <li key={r.name} className="flex flex-col items-center gap-8">
            <span className="relative inline-flex items-center justify-center">
              <ProgressRing value={Number(r.coverage)} size={89} stroke={8} tone={i === 0 ? "supported" : "fg"} />
              <span className="figure absolute font-bold">{r.coverage}</span>
            </span>
            <span className="text-muted">{r.name}</span>
          </li>
        ))}
      </ul>
      <Caption label="Figure 2." source="benchmarks/results/runs/ (test split)">
        Mean coverage on the test split: the share of the evidence each configuration read under the same 0.50 USD
        cap. The same values appear in Table 2.
      </Caption>
    </figure>
  );
}

function ResultsTable() {
  return (
    <figure className="mt-34">
      <div className="overflow-x-auto" role="region" aria-label="Table 2, scrollable" tabIndex={0}>
        <table className="booktabs ui w-full min-w-[560px] text-left">
          <thead>
            <tr>
              <th scope="col" className="label py-8 pr-13">Configuration</th>
              <th scope="col" className="label py-8 pr-13 text-right">Correct</th>
              <th scope="col" className="label py-8 pr-13 text-right">Evidence recall</th>
              <th scope="col" className="label py-8 pr-13 text-right">Coverage</th>
              <th scope="col" className="label py-8 text-right">Cost per run (USD)</th>
            </tr>
          </thead>
          {SPLITS.map(([split, title]) => (
            <tbody key={split}>
              <tr>
                <th colSpan={5} scope="colgroup" className="label border-b border-rule pt-13 pb-8 text-left text-muted">
                  {title}
                </th>
              </tr>
              {RESULTS.filter((r) => r.split === split).map((r) => (
                <tr key={`${split}-${r.name}`}>
                  <th scope="row" className="py-8 pr-13 font-normal">{r.name}</th>
                  <td className="figure py-8 pr-13 text-right">{r.correct}</td>
                  <td className="figure py-8 pr-13 text-right">{r.recall}</td>
                  <td className="figure py-8 pr-13 text-right">{r.coverage}</td>
                  <td className="num py-8 text-right text-cost">{r.cost}</td>
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
      <p className="caption mt-8 sm:hidden">Scroll the table sideways for coverage and cost.</p>
      <p className="ui mt-13 border-l-2 border-rule-strong pl-13">
        <span className="label mr-8">Caveat</span>n = 3 incidents per split and configuration, one run each. Read the
        counts as three observations, not as rates.
      </p>
      <Caption label="Table 2." source="benchmarks/results/runs/ (18 run files; test at commit d5ea1f7, dev at b3aedd4)">
        {CAPTION} Correct counts a diagnosis with the right category and at least one verified essential citation.
        Aggregated by release/results_json.py.
      </Caption>
    </figure>
  );
}

/* The page ---------------------------------------------------------------- */

export function Landing() {
  const index = useRecordingIndex();
  const { state, retry } = index;
  const recordings = state.kind === "ready" ? state.recordings : [];
  const first = recordings[0] ?? null;
  const entry = recordings.find((r) => r.folder === FEATURED) ?? recordings[0] ?? null;
  const featured = useFeatured(entry?.folder ?? null);

  const watch =
    state.kind === "ready" && first ? (
      <a href={runHref(first.folder)} className={`${buttonClass("primary")} no-underline`}>
        Watch a recorded investigation
      </a>
    ) : state.kind === "loading" ? (
      <button type="button" disabled className={buttonClass("primary")}>
        Checking what is available
      </button>
    ) : state.kind === "error" ? (
      <span role="alert" className="ui flex flex-wrap items-center gap-13">
        Could not load the recordings. {state.message}
        <button type="button" onClick={retry} className={buttonClass("secondary")}>
          Try again
        </button>
      </span>
    ) : (
      <span className="ui text-muted">No recorded run is published yet.</span>
    );

  return (
    <>
      <SkipLink target="content">Skip to content</SkipLink>
      <SiteHeader />
      <main id="content" className="px-21">
        <article className="measure mx-auto pb-55">
          <header className="relative isolate pt-55 text-center">
            <div aria-hidden="true" className="wash wash-drift wash-soft absolute -inset-x-21 inset-y-0 -z-10" />
            <p className="label text-muted">Rookwise, technical note</p>
            <h1 className="mt-13 text-title font-bold text-balance sm:text-heading">
              An incident answer you can check, line by&nbsp;line.
            </h1>
            <p className="ui mt-21 text-muted text-balance">
              Built for the Nebius x NVIDIA Global AI Hackathon 2026, on NVIDIA Nemotron models served by Nebius Token
              Factory.
            </p>
            <div className="mt-21">
              <StatusMarks />
            </div>
            <div className="mt-34 flex flex-col items-center gap-13 sm:flex-row sm:justify-center">
              {watch}
              <a href="#results" className={buttonClass("ghost")}>
                See the results
              </a>
            </div>
            <div aria-hidden="true" className="relative mx-auto mt-21 h-[178px] w-full max-w-[377px] sm:h-[233px]">
              <div className="glow absolute left-1/2 top-1/2 size-[178px] -translate-x-1/2 -translate-y-1/2 sm:size-[233px]" />
              <DotRook className="absolute left-1/2 top-1/2 h-[144px] -translate-x-1/2 -translate-y-1/2 sm:h-[178px]" />
            </div>
          </header>

          <section id="abstract" aria-labelledby="abstract-title" className="mt-55 scroll-mt-21 border-y border-rule py-34">
            <h2 id="abstract-title" className="label text-center">Abstract</h2>
            <p className="mt-13">
              Rookwise is an AI incident investigator for small engineering teams that have no dedicated
              SRE. It reads an outage&apos;s logs, metrics and deploy diff under a budget set before the run, and
              returns a diagnosis with a remediation plan. Every claim is checked against the log lines. Unsupported
              claims are withdrawn and shown.
            </p>
          </section>

          {state.kind === "loading" ? (
            <Skeleton className="mt-55 h-72" />
          ) : (
            <ClaimFigure entry={entry} facts={featured?.facts ?? null} />
          )}

          <Section id="problem" n="1" title="Problem">
            <p className="mt-21">
              When a service breaks at 3 a.m., nobody on a small team has time to read thousands of log lines across
              several services. An agent could, but a team has two reasons not to trust one. It can state a root cause
              with confidence and cite log lines that do not exist. And its run has no price tag up front: the bill
              arrives after the run.
            </p>
            <p className="mt-21">
              A large company can absorb a wrong diagnosis. A team of five cannot: no on-call rotation to catch it, no
              budget to rerun it, no room to be wrong twice. So Rookwise does not ask you to trust the model. It makes
              mistakes hard to make, and visible when they happen.
            </p>
          </Section>

          <Section id="method" n="2" title="Method">
            <p className="mt-21">
              Poka-yoke is Japanese for mistake-proofing. Shigeo Shingo formalized it within the Toyota Production
              System in the 1960s: a process should make errors hard to commit and easy to see, instead of asking
              people to be careful. The name comes from a shogi term for avoiding an unthinkably bad move. Rookwise
              applies the same idea to AI-assisted investigation, with six safeguards.
            </p>
            <ol className="mt-21 flex flex-col gap-21">
              {SAFEGUARDS.map(([kind, title, text], i) => (
                <li key={title} className="grid grid-cols-[34px_1fr] gap-x-13">
                  <span className="figure text-muted">2.{i + 1}</span>
                  <div>
                    <p>
                      <strong className="font-semibold">{title}.</strong>{" "}
                      <span className={`label ml-8 inline-flex rounded-full px-13 ${KIND_PILL[kind]}`}>{kind}</span>
                    </p>
                    <p className="mt-8">{text}</p>
                  </div>
                </li>
              ))}
            </ol>
            <p className="ui mt-21 text-muted">
              The labels borrow Shingo&apos;s vocabulary. This is an analogy, not a certification. Source:{" "}
              <a className="text-fg underline" href="https://en.wikipedia.org/wiki/Poka-yoke" rel="noreferrer">
                Wikipedia, Poka-yoke
              </a>
              .
            </p>
            {featured?.team && entry && <TeamTable entry={entry} team={featured.team} />}
          </Section>

          <Section id="results" n="3" title="Results">
            <p className="mt-21">
              Six synthetic incidents with known root causes, three for development and three held out for testing,
              each run once in three configurations: (a) the hierarchy, (b) a single Nemotron Ultra reading the same
              slices, and (c) a single Nemotron Lightning reading the same slices. All three share the slicer, the
              operator prompt, the evidence check and the budget rules.
            </p>
            <div className="wash mt-34 rounded-hero border border-rule px-21 pb-21 sm:px-34 sm:pb-34">
              <ResultsTable />
              <CoverageRings />
            </div>
            <p className="mt-21">
              Verified citations do not prove a diagnosis is correct: a single Lightning run on inc-06 had 6 supported
              claims and the wrong category. And Rookwise is allowed to say it does not know: inconclusive is a result,
              not an error.
            </p>
          </Section>

          <Section id="limitations" n="4" title="Limitations">
            <ul className="mt-21 flex list-disc flex-col gap-13 pl-21">
              <li>The corpus is synthetic. Good scores on it do not prove accuracy on real incidents.</li>
              <li>The samples are small: three incidents per split and configuration, one run each.</li>
              <li>
                A correct diagnosis means the right category plus at least one verified essential citation. A model can
                name the right category for the wrong reason.
              </li>
              <li>Verified citations prove that evidence exists, not that the diagnosis is right.</li>
              <li>Some runs end inconclusive or read only part of the evidence when the budget runs out. The report says so.</li>
              <li>The auditor is a model and may favor outputs like its own. The deterministic check always runs first.</li>
              <li>Rookwise v1 executes nothing and holds no credentials for any system. Approving only records a decision.</li>
            </ul>
          </Section>

          <Section id="reproduce" n="5" title="Reproduce">
            <p className="mt-21">
              Every number in Table 2 comes from the run files in benchmarks/results/runs/. Two scripts recompute them
              from those files only, with no network and no model calls:
            </p>
            <pre className="quote mt-21 overflow-x-auto border-y border-rule py-13">
{`python release/verify_benchmark.py
python release/results_json.py --markdown`}
            </pre>
            <p className="ui mt-13 text-muted">
              The first checks the 18 run files against the committed summaries and known values and prints PASS or
              FAIL per check. The second prints Table 2 as Markdown.
            </p>
            <h3 className="mt-34 text-title">Demo</h3>
            <p className="mt-13">
              The recorded runs replay in the browser: the same events, the same claims, the same ledger. Replaying
              costs nothing and calls no model.
            </p>
            <div className="mt-21">
              <StatusMarks />
            </div>
            <div className="mt-21 flex flex-col items-center gap-13">
              {watch}
              {recordings.length > 1 && (
                <ul className="ui flex flex-wrap justify-center gap-x-21 gap-y-8" aria-label="Every recorded run">
                  {recordings.map((r) => (
                    <li key={r.folder}>
                      <a className="text-fg underline" href={runHref(r.folder)}>
                        {r.summary.title}
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </Section>
        </article>
      </main>
      <SiteFooter />
    </>
  );
}
