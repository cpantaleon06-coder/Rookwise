import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { runHref } from "../App";
import { LiveRunsControl, SiteFooter, SiteHeader, SkipLink } from "../components/chrome";
import { RookMark } from "../components/mark";
import { buttonClass, Label, Skeleton, Stamp } from "../components/ui";
import { LEVEL_WORDS, reasonWords } from "../lib/labels";
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

/** The recording the stamp moment and the hierarchy figure come from. */
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

/** The org chart of one recording, read from its bundle. Null until loaded or when missing. */
function useTeam(folder: string | null): TeamSummary | null {
  const [team, setTeam] = useState<{ folder: string; team: TeamSummary | null } | null>(null);
  useEffect(() => {
    if (!folder) return;
    let cancelled = false;
    fetch(`${BASE}${encodeURIComponent(folder)}/${BUNDLE_FILE}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
      .then((data: unknown) => {
        if (!cancelled) setTeam({ folder, team: teamOf(validateBundle(data).org?.nodes) });
      })
      .catch(() => !cancelled && setTeam({ folder, team: null }));
    return () => {
      cancelled = true;
    };
  }, [folder]);
  return team && team.folder === folder ? team.team : null;
}

/** True once the element has been on screen; the CSS animations wait for it. */
function useSeen<T extends Element>(): [RefObject<T | null>, boolean] {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(() => typeof IntersectionObserver === "undefined");
  useEffect(() => {
    const el = ref.current;
    if (!el || seen) return;
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

function Section({
  id,
  kicker,
  title,
  children,
  className = "",
}: {
  id: string;
  kicker: string;
  title: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      className={`scroll-mt-21 border-t border-line py-89 lg:py-144 ${className}`}
    >
      <div className="flex flex-col items-center text-center">
        <Label>{kicker}</Label>
        <h2 id={`${id}-title`} className="mt-13 max-w-[22ch] text-heading font-semibold tracking-tight">
          {title}
        </h2>
      </div>
      {children}
    </section>
  );
}

/* 1. Hero and the stamp moment ------------------------------------------- */

function lineRange(c: NonNullable<ClaimExcerpt["citation"]>): string {
  return c.line_end !== c.line_start ? `${c.line_start} to ${c.line_end}` : String(c.line_start);
}

function SceneCard({
  claim,
  verified,
  side,
}: {
  claim: ClaimExcerpt;
  verified: boolean;
  side: "left" | "right";
}) {
  const c = claim.citation;
  const delay = verified ? "0ms" : "610ms";
  return (
    <figure
      className={`scene-claim relative flex min-w-0 flex-col gap-21 rounded-lg border p-21 sm:p-34 ${
        verified ? "border-line bg-surface" : "border-berry/40 bg-berry-tint"
      }`}
      style={{ ["--scene-delay" as string]: delay }}
    >
      <div className={`flex ${side === "left" ? "justify-start" : "justify-end"}`}>
        <Stamp kind={verified ? "verified" : "withdrawn"} className="scene-stamp" />
      </div>
      <blockquote className="text-left">
        <p className="wrap-anywhere">{claim.text}</p>
      </blockquote>
      {c && (
        <div className="overflow-hidden rounded-md border border-line bg-ink text-left">
          <p className="label border-b border-line px-13 py-8 text-muted wrap-anywhere">
            {c.source_id}
          </p>
          <div
            className="scene-line grid grid-cols-[auto_1fr] gap-13 px-13 py-8"
            style={{ ["--scene-accent" as string]: verified ? "var(--color-bone)" : "var(--color-berry)" }}
          >
            <span className="num text-muted">{lineRange(c)}</span>
            <span className={`quote ${verified ? "" : "struck scene-strike"}`}>{c.quote}</span>
          </div>
        </div>
      )}
      <figcaption className={`text-left ${verified ? "text-muted" : "text-berry"}`}>
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
      <p className="mx-auto max-w-[55ch] text-center text-muted">
        Two claims from the recording “{entry.summary.title}”, as the evidence check judged them.
      </p>
      <div key={take} className={`scene mt-34 grid gap-21 md:grid-cols-2 md:gap-34 ${seen ? "is-playing" : ""}`}>
        <SceneCard claim={excerpt.verified} verified side="left" />
        <SceneCard claim={excerpt.withdrawn} verified={false} side="right" />
      </div>
      <div className="mt-34 flex justify-center motion-reduce:hidden">
        <button type="button" className={buttonClass("ghost")} onClick={() => setTake((n) => n + 1)}>
          Replay the check
        </button>
      </div>
    </div>
  );
}

function Hero({ state, retry }: ReturnType<typeof useRecordingIndex>) {
  const recordings = state.kind === "ready" ? state.recordings : [];
  const first = recordings[0] ?? null;
  const featured = recordings.find((r) => r.folder === FEATURED) ?? recordings.find((r) => r.excerpt) ?? null;
  return (
    <section aria-labelledby="hero-title" className="py-89 lg:py-144">
      <div className="flex flex-col items-center text-center">
        <h1 id="hero-title" className="max-w-[16ch] text-heading font-semibold tracking-tight sm:text-hero">
          <span className="block">An incident answer</span>
          <span className="block text-muted">you can check, line by line.</span>
        </h1>
        <p className="mt-34 max-w-[42ch] text-muted sm:text-title">
          Rookwise investigates an outage under a budget you set. Before you read the answer, code
          checks every claim against the log.
        </p>
        <div className="mt-55 flex w-full flex-col items-center gap-21">
          {state.kind === "loading" && (
            <button type="button" disabled className={buttonClass("primary")}>
              Checking what is available
            </button>
          )}
          {state.kind === "ready" && first && (
            <a href={runHref(first.folder)} className={buttonClass("primary")}>
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
          <LiveRunsControl centered />
        </div>
      </div>
      {state.kind === "loading" ? (
        <div className="mx-auto mt-89 grid max-w-[1100px] gap-34 md:grid-cols-2">
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
      ) : (
        <StampMoment entry={featured} />
      )}
      {recordings.length > 1 && (
        <nav aria-label="Recorded runs" className="mt-55 flex flex-col items-center gap-8 text-center">
          <Label>Every recorded run</Label>
          <ul className="flex flex-wrap justify-center gap-x-21 gap-y-8">
            {recordings.map((r) => (
              <li key={r.folder}>
                <a className="underline underline-offset-4 hover:text-berry" href={runHref(r.folder)}>
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
    <Section id="poka-yoke" kicker="Mistake-proofing" title="Built on poka-yoke">
      <p className="mx-auto mt-34 max-w-[68ch] text-center text-muted">
        Poka-yoke is Japanese for mistake-proofing. Shigeo Shingo formalized it within the Toyota
        Production System in the 1960s: a process should make errors hard to commit and easy to see,
        instead of asking people to be careful. The name comes from a shogi term for avoiding an
        unthinkably bad move. Rookwise applies the same idea to AI-assisted investigation.
      </p>
      <ol className="mt-55 grid gap-21 sm:grid-cols-2 lg:grid-cols-3 lg:gap-34">
        {SAFEGUARDS.map(([kind, title, text], i) => (
          <li
            key={title}
            className="flex min-w-0 flex-col gap-13 rounded-lg border border-line bg-surface p-21 lg:aspect-[1.618/1] lg:p-34"
          >
            <div className="flex items-center justify-between gap-13">
              <span className="label text-berry">{kind}</span>
              <span className="num text-muted">{String(i + 1).padStart(2, "0")}</span>
            </div>
            <h3 className="text-title font-semibold">{title}</h3>
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

function Connector() {
  return <span aria-hidden="true" className="mx-auto block h-[34px] w-px bg-line-strong" />;
}

function LevelRow({ level, children }: { level: TeamSummary["levels"][number]; children?: ReactNode }) {
  return (
    <li className="flex flex-col items-center gap-13">
      {children}
      <p className="flex flex-wrap items-baseline justify-center gap-x-13 gap-y-8">
        <span className="font-semibold">
          {level.count} {(LEVEL_WORDS[level.level] ?? level.level).toLowerCase()}
          {level.count === 1 ? "" : "s"}
        </span>
        {level.models.map((m) => (
          <span key={m.model} className="num text-muted">
            {m.model}
            {level.models.length > 1 ? ` (${m.count})` : ""}
          </span>
        ))}
      </p>
    </li>
  );
}

function Hierarchy({ team, title }: { team: TeamSummary; title: string }) {
  const [ref, seen] = useSeen<HTMLOListElement>();
  const top = team.levels.filter((l) => l.level === "vp" || l.level === "director");
  const managers = team.levels.find((l) => l.level === "manager");
  const operators = team.levels.find((l) => l.level === "operator");
  const auditor = team.levels.find((l) => l.level === "auditor");
  const mainModel = operators?.models[0]?.model;
  return (
    <figure className="mx-auto mt-55 max-w-[89ch]">
      <ol ref={ref} aria-label="Team of the recorded run" className={`lights flex flex-col ${seen ? "is-playing" : ""}`}>
        {top.map((level) => (
          <LevelRow key={level.level} level={level}>
            <span className="flex size-[55px] items-center justify-center rounded-md border border-bone">
              <RookMark className="h-[34px] w-[21px]" />
            </span>
          </LevelRow>
        ))}
        {managers && (
          <>
            <Connector />
            <LevelRow level={managers}>
              <span aria-hidden="true" className="flex flex-wrap justify-center gap-13">
                {Array.from({ length: managers.count }, (_, i) => (
                  <span key={i} className="size-[21px] rounded-sm border-2 border-bone" />
                ))}
              </span>
            </LevelRow>
          </>
        )}
        {operators && (
          <>
            <Connector />
            <LevelRow level={operators}>
              <span aria-hidden="true" className="flex max-w-[55ch] flex-wrap justify-center gap-8">
                {team.operators.map((model, i) => (
                  <span
                    key={i}
                    className={`light size-[13px] border-2 border-bone ${model === mainModel ? "rounded-full" : "rounded-[2px]"}`}
                    style={{ ["--light-delay" as string]: `${i * 21}ms` }}
                  />
                ))}
              </span>
            </LevelRow>
          </>
        )}
        <Connector />
        <li className="flex flex-col items-center gap-8">
          <span className="label rounded-full border border-berry px-13 text-berry">Evidence check</span>
          <span className="text-muted">Code, no model</span>
        </li>
        {auditor && (
          <>
            <Connector />
            <LevelRow level={auditor} />
          </>
        )}
        <Connector />
        <li className="flex flex-col items-center gap-8">
          <span className="label rounded-full bg-bone px-13 text-ink">You</span>
          <span className="text-muted">Approve or reject</span>
        </li>
      </ol>
      <figcaption className="mt-34 text-center text-muted">
        The team of the recording “{title}”, from its org chart.
        {operators && operators.models.length > 1 && " Round dots ran the most common operator model; square ones ran the other."}
      </figcaption>
    </figure>
  );
}

function HowItWorks({ entry }: { entry: IndexEntry | null }) {
  const team = useTeam(entry?.folder ?? null);
  return (
    <Section
      id="how-it-works"
      kicker="How it works"
      title="Cheap models read. A strong model judges. Code verifies. A human decides."
    >
      {team && entry ? (
        <Hierarchy team={team} title={entry.summary.title} />
      ) : (
        <Skeleton className="mx-auto mt-55 h-96 max-w-[55ch]" />
      )}
    </Section>
  );
}

/* 5. Results -------------------------------------------------------------- */

const RESULTS = [
  ["(a) hierarchy", "2 of 3", "0.920", "0.250"],
  ["(b) single Ultra", "0 of 3", "0.107", "0.386"],
  ["(c) single Lightning", "1 of 3", "0.705", "0.119"],
] as const;

const CAPTION =
  "Synthetic incidents, 3 per configuration, same 0.50 USD cap for every configuration, test split not used while tuning.";

function Results() {
  return (
    <Section id="results" kicker="Results" title="Three configurations on the test split">
      <div className="mx-auto mt-55 max-w-[1100px]">
        <ul className="grid gap-21 sm:hidden">
          {RESULTS.map(([name, correct, coverage, cost]) => (
            <li key={name} className="rounded-lg border border-line bg-surface p-21 text-center">
              <h3 className="font-semibold">{name}</h3>
              <dl className="mt-13 grid grid-cols-3 gap-8">
                <div>
                  <dt className="label text-muted">Correct</dt>
                  <dd className="num text-title">{correct}</dd>
                </div>
                <div>
                  <dt className="label text-muted">Coverage</dt>
                  <dd className="num text-title">{coverage}</dd>
                </div>
                <div>
                  <dt className="label text-muted">USD</dt>
                  <dd className="num text-title">{cost}</dd>
                </div>
              </dl>
            </li>
          ))}
          <li className="text-center text-muted">{CAPTION}</li>
        </ul>
        <table className="hidden w-full border-collapse text-center sm:table">
          <caption className="caption-bottom pt-21 text-muted">{CAPTION}</caption>
          <thead>
            <tr className="border-b border-line-strong">
              <th scope="col" className="label py-13 text-left text-muted">Configuration</th>
              <th scope="col" className="label py-13 text-muted">Correct diagnoses</th>
              <th scope="col" className="label py-13 text-muted">Mean coverage</th>
              <th scope="col" className="label py-13 text-muted">Mean cost (USD)</th>
            </tr>
          </thead>
          <tbody>
            {RESULTS.map(([name, correct, coverage, cost], i) => (
              <tr key={name} className="border-b border-line">
                <th scope="row" className={`py-21 text-left font-semibold ${i === 0 ? "text-bone" : "text-muted"}`}>
                  {name}
                </th>
                <td className="num py-21 text-title lg:text-heading">{correct}</td>
                <td className="num py-21 text-title lg:text-heading">{coverage}</td>
                <td className="num py-21 text-title lg:text-heading">{cost}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mx-auto mt-55 max-w-[68ch] text-center sm:text-title">
          Verified citations do not prove a diagnosis is correct: a single Lightning run on inc-06 had
          6 supported claims and the wrong category. And Rookwise is allowed to say it does not know:
          inconclusive is a result, not an error.
        </p>
      </div>
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
    <Section id="limits" kicker="Limits" title="What this does not show">
      <ul className="mx-auto mt-55 grid max-w-[1100px] gap-21 md:grid-cols-3 md:gap-34">
        {LIMITS.map(([title, text]) => (
          <li key={title} className="flex flex-col items-center gap-8 text-center">
            <span className="label text-berry">{title}</span>
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
  const featured = recordings.find((r) => r.folder === FEATURED) ?? recordings[0] ?? null;

  return (
    <>
      <SkipLink target="content">Skip to content</SkipLink>
      <SiteHeader />
      <main id="content" className="mx-auto max-w-[1440px] px-21 lg:px-55">
        <Hero {...index} />

        <Section id="why" kicker="Why it exists" title="A small team cannot afford to be wrong.">
          <p className="mx-auto mt-34 max-w-[55ch] text-center sm:text-title">
            A large company can absorb a wrong diagnosis. A team of five cannot: no on-call rotation to
            catch it, no budget to rerun it, no room to be wrong twice. So Rookwise does not ask you to
            trust the model. It makes mistakes hard to make, and visible when they happen.
          </p>
        </Section>

        <PokaYoke />
        <HowItWorks entry={featured} />
        <Results />
        <Limits />
      </main>
      <SiteFooter />
    </>
  );
}
