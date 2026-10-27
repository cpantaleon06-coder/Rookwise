import { ProgressRing, TeamRings, type NodeTone, type RingNode } from "../components/figures";
import { buttonClass, Label } from "../components/ui";
import { splitOf, SPLIT_WORDS } from "../lib/incidents";
import { AGENT_STATUS_WORDS } from "../lib/labels";
import { atLeastPercent, formatMicros, percentOf, type Micros } from "../lib/money";
import type { Provenance } from "../lib/recording";
import { SPEEDS, type Speed } from "../lib/replay";
import type { AgentState } from "../lib/runState";
import type { RecordingSummary } from "../lib/types";
import type { ReplayControls } from "./useReplay";

const PROVENANCE_WORDS: Record<Provenance, string> = {
  synthetic_fixture: "Recorded run (synthetic, replayed)",
  real_model_output: "Recorded run (measured, replayed)",
  unknown: "Recorded run (replayed)",
};

/** On every screen of a recorded run, never dismissible. One slim line. */
export function RecordedBanner({
  provenance,
  summary,
  notice,
}: {
  provenance: Provenance | null;
  summary: RecordingSummary | null;
  notice: string | null;
}) {
  const split = splitOf(summary?.incident_id);
  return (
    <div role="note" aria-label="Recorded run" className="px-21 pt-13 lg:px-55">
      <p className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-center gap-x-13 gap-y-8 rounded-md bg-violet-tint px-21 py-8 text-center lg:rounded-full">
        <span className="label inline-flex items-center gap-8 text-violet">
          <span aria-hidden="true" className="size-2.5 rounded-full border-2 border-violet" />
          {PROVENANCE_WORDS[provenance ?? "unknown"]}
        </span>
        <span className="text-muted">
          {notice ?? "Replayed at no cost; it cannot be changed."}
          {provenance === "synthetic_fixture" && " The run is a synthetic fixture: its texts and numbers are not model output."}
          {provenance === "real_model_output" && " The model output is real; the incident it investigated is synthetic."}
          {split && ` ${SPLIT_WORDS[split]}`}
        </span>
      </p>
    </div>
  );
}

export function statusTone(label: string): "ok" | "danger" | "neutral" {
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

const AGENT_TONE: Record<string, NodeTone> = {
  done: "lit",
  working: "active",
  hired: "dim",
  idle: "dim",
  failed: "alert",
  stopped: "alert",
};

function teamNodes(agents: AgentState[]) {
  const ops = agents.filter((a) => a.node.level === "operator");
  const counts = new Map<string, number>();
  for (const o of ops) counts.set(o.node.model, (counts.get(o.node.model) ?? 0) + 1);
  const main = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
  const tone = (a: AgentState): NodeTone => AGENT_TONE[a.status] ?? "dim";
  const director = agents.find((a) => a.node.level === "director" || a.node.level === "vp");
  const auditor = agents.find((a) => a.node.level === "auditor");
  return {
    director: director ? tone(director) : ("dim" as NodeTone),
    managers: agents.filter((a) => a.node.level === "manager").map((a): RingNode => ({ tone: tone(a) })),
    operators: ops.map((a): RingNode => ({ tone: tone(a), square: a.node.model !== main })),
    auditor: auditor ? tone(auditor) : null,
  };
}

function statusWords(agents: AgentState[]): string {
  const counts = new Map<string, number>();
  for (const a of agents) {
    const word = (AGENT_STATUS_WORDS[a.status] ?? a.status).toLowerCase();
    counts.set(word, (counts.get(word) ?? 0) + 1);
  }
  return [...counts.entries()].map(([w, n]) => `${n} ${w}`).join(", ");
}

function StatusPill({ tone, children }: { tone: "ok" | "danger" | "neutral" | "warn"; children: string }) {
  const cls =
    tone === "ok"
      ? "bg-teal text-ink"
      : tone === "danger"
        ? "bg-berry text-ink"
        : tone === "warn"
          ? "bg-berry-tint text-berry"
          : "border border-line-strong text-bone";
  return <span className={`label pill inline-flex min-h-[34px] items-center px-13 ${cls}`}>{children}</span>;
}

/**
 * The compact strip at the top of a run: the team as small rings, the budget
 * as a ring with its numbers, and the status pills. Sticky from tablet width.
 */
export function RunHeader({
  status,
  goal,
  simulatedCase,
  budget,
  decisionNeeded,
  agents,
}: {
  status: string;
  goal: string;
  simulatedCase: boolean;
  budget: HeaderBudget;
  decisionNeeded: boolean;
  agents: AgentState[];
}) {
  const { spent, held, cap, stopped } = budget;
  const over = spent !== null && cap !== null && spent > cap;
  const alert = stopped || over || (spent !== null && cap !== null && cap > 0n && atLeastPercent(spent, cap, 80));
  const pct = spent !== null && cap !== null ? Math.min(100, percentOf(spent, cap)) : 0;
  const nodes = teamNodes(agents);
  return (
    <header className="z-20 bg-ink px-21 py-8 md:sticky md:top-0 lg:px-55">
      <div className="card mx-auto grid max-w-[1440px] items-center gap-13 rounded-lg p-13 md:grid-cols-3 md:rounded-full md:px-34">
        <div className="flex min-w-0 items-center gap-13">
          <TeamRings {...nodes} compact className="size-[55px] shrink-0" />
          <div className="min-w-0">
            <Label>Team</Label>
            <p className="wrap-anywhere">
              {agents.length === 0 ? "No agent yet" : `${agents.length} agents: ${statusWords(agents)}`}
            </p>
          </div>
        </div>
        <div className="flex min-w-0 items-center gap-13 md:justify-center">
          <div
            role="meter"
            aria-label="Budget"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={spent === null ? 0 : pct}
            aria-valuetext={
              spent === null || cap === null
                ? "Not started"
                : `Spent ${formatMicros(spent)} of ${formatMicros(cap)} cap, ${formatMicros(held ?? 0n)} reserved`
            }
            className="meter-track shrink-0 rounded-full"
          >
            <ProgressRing value={pct / 100} size={55} stroke={6} tone={alert ? "berry" : "gold"} />
          </div>
          <div className="min-w-0">
          <dl>
            <div className="flex flex-wrap items-baseline gap-x-8">
              <dt><Label>Spent</Label></dt>
              <dd className="num">{spent === null ? "Not started" : formatMicros(spent)}</dd>
            </div>
            <div className="flex flex-wrap items-baseline gap-x-8">
              <dt><Label>Cap</Label></dt>
              <dd className="num">{cap === null ? "Not recorded" : formatMicros(cap)}</dd>
              {held !== null && held > 0n && (
                <>
                  <dt className="sr-only">Reserved</dt>
                  <dd className="num text-muted">({formatMicros(held)} reserved)</dd>
                </>
              )}
            </div>
          </dl>
          {over && spent !== null && cap !== null && (
            <p className="text-berry">Over the cap by {formatMicros(spent - cap)}.</p>
          )}
          </div>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-8 md:justify-end">
          <StatusPill tone={statusTone(status)}>{status}</StatusPill>
          {simulatedCase && <StatusPill tone="neutral">Synthetic</StatusPill>}
          {decisionNeeded && (
            <a href="#decision" onClick={jumpTo("decision")} className="rounded-full">
              <StatusPill tone="warn">Decision needed</StatusPill>
            </a>
          )}
        </div>
      </div>
      <p className="sr-only">Goal: {goal}</p>
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

export function ReplayToolbar({ replay }: { replay: ReplayControls }) {
  const { speed, playing, done, position, total } = replay;
  return (
    <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-center gap-13 px-21 pt-21 lg:px-55">
      <Label>Replay</Label>
      {done ? (
        <button type="button" className={buttonClass("secondary")} onClick={replay.restart}>
          Replay again
        </button>
      ) : playing ? (
        <button type="button" className={buttonClass("secondary")} onClick={replay.pause}>
          Pause
        </button>
      ) : (
        <button type="button" className={buttonClass("primary")} onClick={replay.play}>
          Play
        </button>
      )}
      <div role="radiogroup" aria-label="Replay speed" className="pill flex gap-8 border border-line">
        {SPEEDS.map((s) => (
          <button
            key={s}
            type="button"
            role="radio"
            aria-checked={speed === s}
            onClick={() => replay.setSpeed(s)}
            className={`label pill inline-flex min-h-11 min-w-11 items-center justify-center px-13 ${
              speed === s ? "bg-bone text-ink" : "text-bone hover:bg-raised"
            }`}
          >
            {SPEED_WORDS[s]}
          </button>
        ))}
      </div>
      <span className="figure text-muted" aria-live="off">
        Event {position} of {total}
      </span>
    </div>
  );
}
