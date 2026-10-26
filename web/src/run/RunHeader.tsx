import { LiveRunsControl } from "../components/chrome";
import { Button, Chip, Label, Meter, type Tone } from "../components/ui";
import { formatDate } from "../lib/labels";
import { formatMicros, formatUsd, type Micros } from "../lib/money";
import type { Provenance } from "../lib/recording";
import { SPEEDS, type Speed } from "../lib/replay";
import type { RecordingSummary } from "../lib/types";
import type { ReplayControls } from "./useReplay";

const PROVENANCE_WORDS: Record<Provenance, string> = {
  synthetic_fixture: "Recorded run (synthetic, replayed)",
  real_model_output: "Recorded run (measured, replayed)",
  unknown: "Recorded run (replayed)",
};

/** web/DESIGN.md 3.3: on every screen of a recorded run, never dismissible. */
export function RecordedBanner({
  provenance,
  summary,
  notice,
}: {
  provenance: Provenance | null;
  summary: RecordingSummary | null;
  notice: string | null;
}) {
  const recorded = formatDate(summary?.recorded_at);
  return (
    <div
      role="note"
      aria-label="Recorded run"
      className="border-l-4 border-info bg-info-tint"
    >
      <div className="mx-auto flex max-w-[1440px] flex-col gap-3 px-4 py-3 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
        <div className="min-w-0">
          <p className="label text-info">{PROVENANCE_WORDS[provenance ?? "unknown"]}</p>
          <p className="mt-1 text-sm">
            {notice ?? "Replaying a saved run with its original timing. It costs nothing and cannot be changed."}
            {provenance === "synthetic_fixture" && " The run is a synthetic fixture: its texts and numbers are not model output."}
            {provenance === "real_model_output" && " The model output is real; the incident it investigated is synthetic."}
          </p>
          {summary && (
            <p className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
              {summary.simulated_case && <span>Synthetic incident</span>}
              <span>
                Cost when recorded: <span className="num">{formatUsd(summary.spent_usd)}</span>
              </span>
              {recorded && <span>Recorded {recorded}</span>}
            </p>
          )}
        </div>
        <LiveRunsControl compact />
      </div>
    </div>
  );
}

export function statusTone(label: string): Tone {
  if (label === "Finished") return "ok";
  if (label === "Failed" || label === "Partial" || label === "Cancelled") return "danger";
  return "neutral";
}

export interface HeaderBudget {
  spent: Micros | null;
  held: Micros | null;
  cap: Micros | null;
  stopped: boolean;
}

export function RunHeader({
  status,
  goal,
  simulatedCase,
  budget,
  decisionNeeded,
}: {
  status: string;
  goal: string;
  simulatedCase: boolean;
  budget: HeaderBudget;
  decisionNeeded: boolean;
}) {
  const { spent, held, cap, stopped } = budget;
  const over = spent !== null && cap !== null && spent > cap;
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-bg/95 backdrop-blur supports-[backdrop-filter]:bg-bg/85">
      <div className="mx-auto flex max-w-[1440px] flex-col gap-3 px-4 py-3 sm:px-6 lg:px-8">
        <div className="flex flex-wrap items-center gap-2">
          <a href="#/" className="mr-2 font-semibold tracking-tight">
            Rookwise
          </a>
          <Chip tone="info">Recorded</Chip>
          <Chip tone={statusTone(status)}>{status}</Chip>
          {simulatedCase && <Chip>Synthetic incident</Chip>}
          {decisionNeeded && (
            <a href="#decision" onClick={jumpTo("decision")} className="rounded-full">
              <Chip tone="warn">Decision needed</Chip>
            </a>
          )}
        </div>
        <p className="hidden truncate text-sm text-muted sm:block" title={goal}>
          <span className="sr-only">Goal: </span>
          {goal}
        </p>
        <div className="grid gap-2 sm:grid-cols-[auto_1fr] sm:items-center sm:gap-6">
          <dl className="grid grid-cols-3 divide-x divide-line">
            <div className="min-w-0 pr-3">
              <dt><Label>Spent</Label></dt>
              <dd className="num text-sm sm:text-base">{spent === null ? "Not started" : formatMicros(spent)}</dd>
            </div>
            <div className="min-w-0 px-3">
              <dt><Label>Reserved</Label></dt>
              <dd className="num text-sm sm:text-base">{held === null ? "Not started" : formatMicros(held)}</dd>
            </div>
            <div className="min-w-0 pl-3">
              <dt><Label>Cap</Label></dt>
              <dd className="num text-sm sm:text-base">{cap === null ? "Not recorded" : formatMicros(cap)}</dd>
            </div>
          </dl>
          <div className="flex min-w-0 flex-col gap-1">
            <Meter spent={spent} held={held} cap={cap} stopped={stopped} />
            {over && spent !== null && cap !== null && (
              <p className="text-sm text-danger">Over the cap by {formatMicros(spent - cap)}.</p>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}

/** In-page jump that leaves the hash route alone and moves focus to the section. */
export function jumpTo(id: string) {
  return (e: { preventDefault: () => void }) => {
    e.preventDefault();
    const el = document.getElementById(id);
    if (!el) return;
    el.scrollIntoView();
    if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "-1");
    el.focus({ preventScroll: true });
  };
}

const SPEED_WORDS: Record<Speed, string> = { "1x": "1x", "4x": "4x", instant: "Instant" };

const JUMPS = [
  ["decision", "Decision"],
  ["evidence", "Evidence"],
  ["team", "Team"],
  ["tasks", "Tasks"],
  ["feed", "Feed"],
  ["budget", "Budget"],
  ["chat", "Chat"],
] as const;

export function ReplayToolbar({ replay }: { replay: ReplayControls }) {
  const { speed, playing, done, position, total } = replay;
  return (
    <div className="mx-auto flex max-w-[1440px] flex-col gap-3 px-4 pt-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
      <div className="flex flex-wrap items-center gap-2">
        <Label className="mr-1">Replay</Label>
        {done ? (
          <Button onClick={replay.restart}>Replay again</Button>
        ) : playing ? (
          <Button onClick={replay.pause}>Pause</Button>
        ) : (
          <Button onClick={replay.play}>Play</Button>
        )}
        <div role="radiogroup" aria-label="Replay speed" className="flex gap-1">
          {SPEEDS.map((s) => (
            <button
              key={s}
              type="button"
              role="radio"
              aria-checked={speed === s}
              onClick={() => replay.setSpeed(s)}
              className={`label inline-flex min-h-11 min-w-11 items-center justify-center rounded-full px-3 ${
                speed === s ? "bg-primary text-on-primary" : "border border-line-strong text-ink hover:bg-raised"
              }`}
            >
              {SPEED_WORDS[s]}
            </button>
          ))}
        </div>
        <span className="num text-sm text-muted" aria-live="off">
          Event {position} of {total}
        </span>
      </div>
      <nav aria-label="Sections" className="-mx-4 overflow-x-auto px-4 lg:mx-0 lg:px-0">
        <ul className="flex w-max gap-1">
          {JUMPS.map(([id, label]) => (
            <li key={id}>
              <a
                href={`#${id}`}
                onClick={jumpTo(id)}
                className="label inline-flex min-h-11 items-center rounded-full px-3 text-muted hover:bg-raised hover:text-ink"
              >
                {label}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
