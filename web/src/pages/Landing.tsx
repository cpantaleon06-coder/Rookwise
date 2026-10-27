import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { runHref } from "../App";
import { LIVE_RUNS_NOTE, LiveRunsButton, SiteFooter, SiteHeader, SkipLink } from "../components/chrome";
import { DotRook, Glyph, MirroredArcs, ProgressRing, TeamRings, type RingNode } from "../components/figures";
import { buttonClass, Label, Skeleton, Stamp } from "../components/ui";
import { runFacts, type RunFacts } from "../lib/facts";
import { LEVEL_WORDS, reasonWords, VERDICT_WORDS } from "../lib/labels";
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

/** The recording the hero, the stamp moment and the rings come from. */
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

/** True once the element has been on screen; motion waits for it, the final state does not. */
function useSeen<T extends Element>(): [RefObject<T | null>, boolean] {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || seen || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setSeen(true);
          io.disconnect();
        }
      },
      { threshold: 0.38 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [seen]);
  return [ref, seen];
}

function TagPill({ children, tone = "bone" }: { children: ReactNode; tone?: "bone" | "berry" }) {
  return (
    <span className="label pill inline-flex min-h-[34px] items-center gap-8 border border-line bg-raised px-13 text-bone">
      <span aria-hidden="true" className={`size-2 rounded-full ${tone === "berry" ? "bg-berry" : "bg-bone"}`} />
      {children}
    </span>
  );
}

function Section({
  id,
  tag,
  title,
  children,
}: {
  id: string;
  tag: string;
  title: ReactNode;
  children: ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-21 py-89 lg:py-144">
      <div className="flex flex-col items-center text-center">
        <TagPill>{tag}</TagPill>
        <h2 id={`${id}-title`} className="mt-21 max-w-[22ch] text-heading font-semibold tracking-tight text-balance">
          {title}
        </h2>
      </div>
      {children}
    </section>
  );
}

/* 1. Hero ----------------------------------------------------------------- */

function FactPill({ dot, children }: { dot: "bone" | "berry"; children: ReactNode }) {
  return (
    <span className="num pill card inline-flex min-h-11 max-w-full items-center gap-8 px-21 shadow-[0_13px_34px_-21px_#142030]">
      <span aria-hidden="true" className={`size-2.5 shrink-0 rounded-full ${dot === "berry" ? "bg-berry" : "bg-bone"}`} />
      <span className="wrap-anywhere">{children}</span>
    </span>
  );
}

function factPills(facts: RunFacts | null): { key: string; dot: "bone" | "berry"; text: string }[] {
  if (!facts) return [];
  const pills: { key: string; dot: "bone" | "berry"; text: string }[] = [];
  if (facts.verifiedClaimId) pills.push({ key: "verified", dot: "bone", text: `${facts.verifiedClaimId} verified` });
  if (facts.withdrawnReason)
    pills.push({ key: "withdrawn", dot: "berry", text: `${facts.withdrawnClaimId ?? "claim"} withdrawn: ${facts.withdrawnReason}` });
  if (facts.spentUsd && facts.capUsd)
    pills.push({ key: "budget", dot: "bone", text: `${formatUsd(facts.spentUsd)} of ${formatUsd(facts.capUsd)} cap` });
  if (facts.slicesRead !== null)
    pills.push({
      key: "slices",
      dot: facts.unreadRanges ? "berry" : "bone",
      text: `${facts.slicesRead} slices read${facts.unreadRanges !== null ? `, ${facts.unreadRanges} unread` : ""}`,
    });
  return pills;
}

/** Floating pill positions, mirrored about the axis: left, right, left, right. */
const PILL_SPOTS = [
  "lg:left-0 lg:top-[21%]",
  "lg:right-0 lg:top-[21%]",
  "lg:left-[5%] lg:top-[66%]",
  "lg:right-[5%] lg:top-[66%]",
];

function HeroObject({ facts }: { facts: RunFacts | null }) {
  const pills = factPills(facts);
  return (
    <div id="hero-object" className="relative mx-auto mt-21 w-full max-w-[987px]">
      <div className="relative h-[377px] md:h-[610px]">
        <div aria-hidden="true" className="grid-frame absolute inset-0" />
        <span aria-hidden="true" className="crosshair left-0 top-0" />
        <span aria-hidden="true" className="crosshair right-0 top-0" />
        <span aria-hidden="true" className="crosshair bottom-0 left-0" />
        <span aria-hidden="true" className="crosshair bottom-0 right-0" />
        <MirroredArcs className="absolute inset-0 h-full w-full" />
        <div
          aria-hidden="true"
          className="glow absolute left-1/2 top-1/2 size-[322px] -translate-x-1/2 -translate-y-1/2 md:size-[521px]"
        />
        <DotRook className="absolute left-1/2 top-1/2 h-[289px] -translate-x-1/2 -translate-y-1/2 md:h-[466px]" />
        {pills.map((p, i) => (
          <div key={p.key} aria-hidden="true" className={`absolute hidden lg:block ${PILL_SPOTS[i]}`}>
            <FactPill dot={p.dot}>{p.text}</FactPill>
          </div>
        ))}
      </div>
      {pills.length > 0 && (
        <ul aria-label="From the recorded run" className="mt-21 grid grid-cols-1 justify-items-center gap-8 lg:sr-only">
          {pills.map((p) => (
            <li key={p.key} className="max-w-full">
              <FactPill dot={p.dot}>{p.text}</FactPill>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function tickerFacts(facts: RunFacts | null): string[] {
  if (!facts) return [];
  const out: string[] = [];
  if (facts.spentUsd) out.push(`Spent ${formatUsd(facts.spentUsd)}`);
  if (facts.capUsd) out.push(`Cap ${formatUsd(facts.capUsd)}`);
  if (facts.slicesRead !== null) out.push(`${facts.slicesRead} slices read`);
  if (facts.supported !== null) out.push(`${facts.supported} claims supported`);
  if (facts.withdrawn !== null) out.push(`${facts.withdrawn} claims withdrawn`);
  if (facts.operators !== null) out.push(`${facts.operators} operators`);
  if (facts.auditVerdict) out.push(`Audit: ${(VERDICT_WORDS[facts.auditVerdict] ?? facts.auditVerdict).toLowerCase()}`);
  if (facts.category) out.push(`Category ${facts.category}`);
  return out;
}

function Ticker({ facts, title }: { facts: RunFacts | null; title: string | null }) {
  const items = tickerFacts(facts);
  if (items.length === 0) return null;
  const row = (copy: boolean) => (
    <ul aria-hidden={copy || undefined} className={`flex shrink-0 items-center ${copy ? "ticker-copy" : ""}`}>
      {items.map((item) => (
        <li key={item} className="num flex items-center gap-21 whitespace-nowrap px-21">
          <span aria-hidden="true" className="size-2 rounded-full bg-berry" />
          {item}
        </li>
      ))}
    </ul>
  );
  return (
    <div className="mt-55">
      <p className="sr-only">Facts of the recorded run {title}:</p>
      <div className="ticker pill card overflow-hidden py-13">
        <div className="ticker-track">
          {row(false)}
          {row(true)}
        </div>
      </div>
      {title && <p className="mt-13 text-center text-muted">From the recording “{title}”.</p>}
    </div>
  );
}

function lineRange(c: NonNullable<ClaimExcerpt["citation"]>): string {
  return c.line_end !== c.line_start ? `${c.line_start} to ${c.line_end}` : String(c.line_start);
}

function SceneCard({ claim, verified }: { claim: ClaimExcerpt; verified: boolean }) {
  const c = claim.citation;
  return (
    <figure
      className={`scene-claim relative flex min-w-0 flex-col gap-21 rounded-lg p-21 sm:p-34 ${
        verified ? "card" : "border border-berry/40 bg-berry-tint"
      }`}
      style={{ ["--scene-delay" as string]: verified ? "0ms" : "377ms" }}
    >
      <div className={`flex ${verified ? "justify-start" : "justify-end"}`}>
        {/* Scales from its inner side, so the stamp-in never reaches past the card edge. */}
        <Stamp kind={verified ? "verified" : "withdrawn"} className={`scene-stamp ${verified ? "origin-left" : "origin-right"}`} />
      </div>
      <blockquote>
        <p className="wrap-anywhere">{claim.text}</p>
      </blockquote>
      {c && (
        <div className="overflow-hidden rounded-md border border-line bg-ink">
          <p className="label wrap-anywhere border-b border-line px-13 py-8 text-muted">{c.source_id}</p>
          <div
            className={`scene-line grid grid-cols-[auto_1fr] gap-13 px-13 py-8 ${
              verified ? "bg-raised shadow-[inset_3px_0_0_#eae4d3]" : "bg-berry-tint shadow-[inset_3px_0_0_#ff5c8d]"
            }`}
          >
            <span className="num text-muted">{lineRange(c)}</span>
            <span className={`quote ${verified ? "" : "struck scene-strike"}`}>{c.quote}</span>
          </div>
        </div>
      )}
      <figcaption className={verified ? "text-muted" : "text-berry"}>
        {verified
          ? c
            ? `The quote is in line ${lineRange(c)} of ${c.source_id}. The claim stands.`
            : "The quotes are in the cited lines. The claim stands."
          : `${reasonWords(String(claim.reason))}. The claim is withdrawn and shown with its reason.`}
      </figcaption>
    </figure>
  );
}

function StampMoment({ entry }: { entry: IndexEntry | null }) {
  const [ref, seen] = useSeen<HTMLDivElement>();
  const [take, setTake] = useState(0);
  const excerpt = entry?.excerpt;
  if (!entry || !excerpt?.verified || !excerpt.withdrawn) return null;
  return (
    <div ref={ref} className="mx-auto mt-89 max-w-[1100px]">
      <p className="mx-auto max-w-[55ch] text-center text-muted text-balance">
        Two claims from the recording “{entry.summary.title}”, as the evidence check judged them.
      </p>
      <div
        key={take}
        className={`scene mt-34 grid gap-21 md:grid-cols-2 md:gap-34 ${seen || take > 0 ? "is-playing" : ""}`}
      >
        <SceneCard claim={excerpt.verified} verified />
        <SceneCard claim={excerpt.withdrawn} verified={false} />
      </div>
      <div className="mt-34 flex justify-center motion-reduce:hidden">
        <button type="button" className={buttonClass("secondary")} onClick={() => setTake((n) => n + 1)}>
          Replay the check
        </button>
      </div>
    </div>
  );
}

function Hero({ index, featured }: { index: ReturnType<typeof useRecordingIndex>; featured: Featured | null }) {
  const { state, retry } = index;
  const recordings = state.kind === "ready" ? state.recordings : [];
  const first = recordings[0] ?? null;
  const entry = recordings.find((r) => r.folder === FEATURED) ?? recordings.find((r) => r.excerpt) ?? null;
  return (
    <section aria-labelledby="hero-title" className="pt-55 pb-89 lg:pb-144">
      <div className="flex flex-col items-center text-center">
        <TagPill tone="berry">Real model runs, replayed</TagPill>
        <h1 id="hero-title" className="mt-21 max-w-[21ch] text-heading font-semibold tracking-tight text-balance sm:text-hero">
          An incident answer <span className="text-muted">you can check, line by&nbsp;line.</span>
        </h1>
        <p className="mt-21 max-w-[42ch] text-muted text-balance sm:text-title">
          Rookwise investigates an outage under a budget you set. Before you read the answer, code
          checks every claim against the log.
        </p>
        <div className="mt-34 flex w-full flex-col items-center gap-13 sm:flex-row sm:justify-center">
          {state.kind === "loading" && (
            <button type="button" disabled className={buttonClass("primary")}>
              Checking what is available
            </button>
          )}
          {state.kind === "ready" && first && (
            <a href={runHref(first.folder)} className={`${buttonClass("primary")} shadow-[0_0_34px_-8px_#ff5c8d]`}>
              Watch a recorded run
            </a>
          )}
          {state.kind === "ready" && !first && <p className="text-muted">No recorded run is published yet.</p>}
          {state.kind === "error" && (
            <div role="alert" className="flex flex-col items-center gap-8">
              <p>Could not load the recordings. {state.message}</p>
              <button type="button" onClick={retry} className={buttonClass("secondary")}>
                Try again
              </button>
            </div>
          )}
          <LiveRunsButton />
        </div>
        <p id="live-runs-note" className="mt-13 max-w-[42ch] text-muted text-balance">
          {LIVE_RUNS_NOTE}
        </p>
      </div>
      <HeroObject facts={featured?.facts ?? null} />
      <Ticker facts={featured?.facts ?? null} title={entry?.summary.title ?? null} />
      {state.kind === "loading" ? (
        <div className="mx-auto mt-89 grid max-w-[1100px] gap-34 md:grid-cols-2">
          <Skeleton className="h-72 rounded-lg" />
          <Skeleton className="h-72 rounded-lg" />
        </div>
      ) : (
        <StampMoment entry={entry} />
      )}
      {recordings.length > 1 && (
        <nav aria-label="Recorded runs" className="mt-55 flex flex-col items-center gap-13 text-center">
          <Label>Every recorded run</Label>
          <ul className="flex flex-wrap justify-center gap-8">
            {recordings.map((r) => (
              <li key={r.folder}>
                <a className={buttonClass("secondary")} href={runHref(r.folder)}>
                  {r.summary.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      )}
    </section>
  );
}

/* 3. Poka-yoke ------------------------------------------------------------ */

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

function PokaYoke() {
  return (
    <Section id="poka-yoke" tag="Mistake-proofing" title="Built on poka-yoke">
      <p className="mx-auto mt-34 max-w-[68ch] text-center text-muted">
        Poka-yoke is Japanese for mistake-proofing. Shigeo Shingo formalized it within the Toyota
        Production System in the 1960s: a process should make errors hard to commit and easy to see,
        instead of asking people to be careful. The name comes from a shogi term for avoiding an
        unthinkably bad move. Rookwise applies the same idea to AI-assisted investigation.
      </p>
      <ol className="mt-55 grid gap-21 sm:grid-cols-2 lg:grid-cols-3 lg:gap-34">
        {SAFEGUARDS.map(([kind, title, text], i) => (
          <li key={title} className="card flex min-w-0 flex-col gap-21 rounded-lg p-21 lg:p-34">
            <div className="flex items-start justify-between gap-13">
              <Glyph kind={i as 0 | 1 | 2 | 3 | 4 | 5} className="size-[55px] shrink-0" />
              <span className="label pill inline-flex min-h-[34px] items-center border border-berry px-13 text-berry">
                {kind}
              </span>
            </div>
            <h3 className="text-title font-semibold text-balance">{title}</h3>
            <p className="text-muted">{text}</p>
          </li>
        ))}
      </ol>
      <p className="mx-auto mt-34 max-w-[68ch] text-center text-muted">
        The labels borrow Shingo&apos;s vocabulary. This is an analogy, not a certification. Source:{" "}
        <a
          className="underline underline-offset-4 hover:text-bone"
          href="https://en.wikipedia.org/wiki/Poka-yoke"
          rel="noreferrer"
        >
          Wikipedia, Poka-yoke
        </a>
        .
      </p>
    </Section>
  );
}

/* 4. How it works --------------------------------------------------------- */

function levelWords(level: TeamSummary["levels"][number]): string {
  const word = (LEVEL_WORDS[level.level] ?? level.level).toLowerCase();
  return `${level.count} ${word}${level.count === 1 ? "" : "s"}`;
}

function GatePill({ kicker, title, tone }: { kicker: string; title: string; tone: "bone" | "berry" }) {
  return (
    <div className="flex flex-col items-center gap-8 text-center">
      <span
        className={`label pill inline-flex min-h-11 items-center px-21 ${
          tone === "berry" ? "border border-berry text-berry" : "bg-bone text-ink"
        }`}
      >
        {title}
      </span>
      <span className="text-muted">{kicker}</span>
    </div>
  );
}

function Rings({ team, title }: { team: TeamSummary; title: string }) {
  const [ref, seen] = useSeen<HTMLDivElement>();
  const managers = team.levels.find((l) => l.level === "manager");
  const operators = team.levels.find((l) => l.level === "operator");
  const legend = team.levels;
  const mainModel = operators?.models[0]?.model;
  const ops: RingNode[] = team.operators.map((m) => ({ tone: "lit", square: m !== mainModel }));
  const mgrs: RingNode[] = Array.from({ length: managers?.count ?? 0 }, () => ({ tone: "lit" }));
  return (
    <figure className="mt-55">
      <div className="grid grid-cols-2 items-center gap-x-13 gap-y-34 md:grid-cols-[1fr_auto_1fr] md:gap-34">
        <div className="order-2 md:order-1 md:justify-self-end">
          <GatePill title="Evidence check" kicker="Code, no model" tone="berry" />
        </div>
        <div ref={ref} className={`lights relative order-1 col-span-2 mx-auto w-full max-w-[466px] md:order-2 md:col-span-1 ${seen ? "is-playing" : ""}`}>
          <div aria-hidden="true" className="glow absolute left-1/2 top-1/2 size-[89%] -translate-x-1/2 -translate-y-1/2" />
          <TeamRings
            director="lit"
            managers={mgrs}
            operators={ops}
            auditor={team.levels.some((l) => l.level === "auditor") ? "lit" : null}
            lights
            className="relative w-full"
          />
        </div>
        <div className="order-3 md:justify-self-start">
          <GatePill title="You decide" kicker="Approve or reject" tone="bone" />
        </div>
      </div>
      <ul aria-label="Team of the recorded run" className="mx-auto mt-34 grid max-w-[987px] gap-13 sm:grid-cols-2">
        {legend.map((level) => (
          <li key={level.level} className="card flex flex-col items-center gap-8 rounded-md p-21 text-center">
            <span className="font-semibold">
              {level.level === "director"
                ? "Center"
                : level.level === "manager"
                  ? "Inner ring"
                  : level.level === "operator"
                    ? "Outer ring"
                    : level.level === "auditor"
                      ? "Dashed ring"
                      : "Ring"}
              : {levelWords(level)}
            </span>
            <span className="flex flex-wrap justify-center gap-x-13 gap-y-8">
              {level.models.map((m) => (
                <span key={m.model} className="num text-muted">
                  {m.model}
                  {level.models.length > 1 ? ` (${m.count})` : ""}
                </span>
              ))}
            </span>
          </li>
        ))}
      </ul>
      <figcaption className="mt-21 text-center text-muted text-balance">
        The team of the recording “{title}”, from its org chart.
        {operators && operators.models.length > 1 && " Round dots ran the most common operator model; square ones ran the other."}
      </figcaption>
    </figure>
  );
}

function HowItWorks({ entry, team }: { entry: IndexEntry | null; team: TeamSummary | null }) {
  return (
    <Section
      id="how-it-works"
      tag="How it works"
      title="Cheap models read. A strong model judges. Code verifies. A human decides."
    >
      {team && entry ? (
        <Rings team={team} title={entry.summary.title} />
      ) : (
        <Skeleton className="mx-auto mt-55 aspect-square max-w-[466px] rounded-full" />
      )}
    </Section>
  );
}

/* 5. Results -------------------------------------------------------------- */

const RESULTS = [
  { name: "(a) hierarchy", correct: 2, coverage: "0.920", cost: "0.250" },
  { name: "(b) single Ultra", correct: 0, coverage: "0.107", cost: "0.386" },
  { name: "(c) single Lightning", correct: 1, coverage: "0.705", cost: "0.119" },
] as const;

const CAPTION =
  "Synthetic incidents, 3 per configuration, same 0.50 USD cap for every configuration, test split not used while tuning.";

function Results() {
  return (
    <Section id="results" tag="Results, test split" title="Three configurations, the same cap">
      <ul className="mx-auto mt-55 grid max-w-[1100px] gap-21 md:grid-cols-3 md:gap-34">
        {RESULTS.map((r, i) => (
          <li key={r.name} className="card relative flex flex-col items-center gap-21 overflow-hidden rounded-lg p-34 text-center">
            <span className={`label pill relative inline-flex min-h-[34px] items-center px-13 ${i === 0 ? "bg-bone text-ink" : "border border-line-strong text-bone"}`}>
              {r.name}
            </span>
            <p className="relative">
              <span className="relative block">
                {i === 0 && (
                  <span aria-hidden="true" className="glow absolute left-1/2 top-1/2 size-[121px] -translate-x-1/2 -translate-y-1/2" />
                )}
                <span className="num relative block text-display font-semibold">{r.correct}</span>
              </span>
              <span className="label text-muted">of 3 correct</span>
            </p>
            <div className="relative flex items-center gap-13">
              <ProgressRing value={Number(r.coverage)} size={55} stroke={6} tone={i === 0 ? "berry" : "bone"} />
              <span className="flex flex-col items-start">
                <span className="num text-title">{r.coverage}</span>
                <span className="label text-muted">mean coverage</span>
              </span>
            </div>
            <p className="relative flex flex-col items-center">
              <span className="num text-title">{r.cost} USD</span>
              <span className="label text-muted">mean cost</span>
            </p>
          </li>
        ))}
      </ul>
      <p className="mx-auto mt-34 max-w-[68ch] text-center text-muted">{CAPTION}</p>
      <p className="mx-auto mt-55 max-w-[68ch] text-center text-balance sm:text-title">
        Verified citations do not prove a diagnosis is correct: a single Lightning run on inc-06 had 6
        supported claims and the wrong category. And Rookwise is allowed to say it does not know:
        inconclusive is a result, not an error.
      </p>
    </Section>
  );
}

/* 6. Limits --------------------------------------------------------------- */

const LIMITS = [
  ["Synthetic corpus", "The incidents are generated logs, metrics and diffs, not a real outage."],
  ["Small samples", "Three test incidents per configuration, one run each."],
  ["Executes nothing", "Rookwise v1 only recommends. Approving records your decision in this tab and runs nothing."],
] as const;

function Limits() {
  return (
    <Section id="limits" tag="Limits" title="What this does not show">
      <ul className="mx-auto mt-55 grid max-w-[1100px] gap-21 md:grid-cols-3 md:gap-34">
        {LIMITS.map(([title, text]) => (
          <li key={title} className="card flex flex-col items-center gap-13 rounded-lg p-34 text-center">
            <span className="label pill inline-flex min-h-[34px] items-center border border-berry px-13 text-berry">{title}</span>
            <p className="text-muted">{text}</p>
          </li>
        ))}
      </ul>
    </Section>
  );
}

export function Landing() {
  const index = useRecordingIndex();
  const recordings = index.state.kind === "ready" ? index.state.recordings : [];
  const entry = recordings.find((r) => r.folder === FEATURED) ?? recordings[0] ?? null;
  const featured = useFeatured(entry?.folder ?? null);

  return (
    <>
      <SkipLink target="content">Skip to content</SkipLink>
      <SiteHeader />
      <main id="content" className="mx-auto max-w-[1440px] px-21 lg:px-55">
        <Hero index={index} featured={featured} />

        <Section id="why" tag="Why it exists" title="A small team cannot afford to be wrong.">
          <p className="mx-auto mt-34 max-w-[55ch] text-center text-balance sm:text-title">
            A large company can absorb a wrong diagnosis. A team of five cannot: no on-call rotation to
            catch it, no budget to rerun it, no room to be wrong twice. So Rookwise does not ask you to
            trust the model. It makes mistakes hard to make, and visible when they happen.
          </p>
        </Section>

        <PokaYoke />
        <HowItWorks entry={entry} team={featured?.team ?? null} />
        <Results />
        <Limits />
      </main>
      <SiteFooter />
    </>
  );
}
