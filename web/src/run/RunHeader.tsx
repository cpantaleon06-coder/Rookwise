import { buttonClass, Label, Meter } from "../components/ui";
import { splitOf, SPLIT_WORDS } from "../lib/incidents";
import { formatDate, LEVEL_WORDS } from "../lib/labels";
import { formatMicros, type Micros } from "../lib/money";
import type { Provenance } from "../lib/recording";
import { SPEEDS, type Speed } from "../lib/replay";
import type { AgentState } from "../lib/runState";
import type { RecordedBundle, RecordingSummary } from "../lib/types";
import type { ReplayControls } from "./useReplay";

const PROVENANCE_WORDS: Record<Provenance, string> = {
  synthetic_fixture: "Recorded run (synthetic, replayed)",
  real_model_output: "Recorded run (measured, replayed)",
  unknown: "Recorded run (replayed)",
};

/** On every screen of a recorded run, never dismissible: one ruled line of text. */
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
    <div role="note" aria-label="Recorded run" className="border-b border-rule px-21">
      <p className="ui mx-auto max-w-[1100px] py-8 text-center text-muted">
        <span className="label mr-8 text-fg">
          <span aria-hidden="true" className="mr-8">○</span>
          {PROVENANCE_WORDS[provenance ?? "unknown"]}
        </span>
        {notice ?? "Replayed at no cost; it cannot be changed."}
        {provenance === "synthetic_fixture" && " The run is a synthetic fixture: its texts and numbers are not model output."}
        {provenance === "real_model_output" && " The model output is real; the incident it investigated is synthetic."}
        {split && ` ${SPLIT_WORDS[split]}`}
      </p>
    </div>
  );
}

function recordingCommit(bundle: RecordedBundle): string | null {
  const source = (bundle._recording as { diagnosis_source?: { commit?: unknown } } | undefined)?.diagnosis_source;
  return typeof source?.commit === "string" ? source.commit : null;
}

function modelsOf(bundle: RecordedBundle): string[] {
  const nodes = bundle.org?.nodes;
  return Array.isArray(nodes) ? [...new Set(nodes.map((n) => n.model))].sort() : [];
}

/**
 * Where this run comes from, read from the recording only: run id, the date it
 * was recorded, the commit it was recorded at, the models, and whether the
 * incident is synthetic. A field the recording lacks is left out.
 */
export function ProvenanceLine({
  bundle,
  summary,
  folder,
}: {
  bundle: RecordedBundle;
  summary: RecordingSummary;
  folder: string;
}) {
  const commit = recordingCommit(bundle);
  const recorded = formatDate(summary.recorded_at);
  const models = modelsOf(bundle);
  const items: [string, string][] = [["Run", bundle.run.run_id]];
  if (recorded) items.push(["Recorded", recorded]);
  if (commit) items.push(["Commit", commit]);
  if (models.length > 0) items.push(["Models", models.join(", ")]);
  return (
    <div className="ui mt-21 text-muted">
      <dl className="flex flex-wrap justify-center gap-x-21 gap-y-8">
        {items.map(([k, v]) => (
          <div key={k} className="flex min-w-0 items-baseline gap-8">
            <dt className="label">{k}</dt>
            <dd className="num wrap-anywhere text-fg">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-8 flex flex-wrap justify-center gap-x-21 gap-y-8">
        {(summary.simulated_case || bundle.run.simulated_case) && (
          <span className="label">
            <span aria-hidden="true" className="mr-8">△</span>Synthetic incident
          </span>
        )}
        <span className="label">
          <span aria-hidden="true" className="mr-8">○</span>Recorded run, not live
        </span>
        <span className="label">
          <span aria-hidden="true" className="mr-8">■</span>Executes nothing
        </span>
      </p>
      <p className="mt-8 text-center">
        <span className="label mr-8">Source</span>
        <span className="num wrap-anywhere">web/public/recordings/{folder}/recorded_run.json</span>
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

/**
 * The team as the recording describes it. Operators get a final state from
 * their task results; the recording keeps no final state for the director,
 * managers or auditor, so for them only the count and the model are shown.
 */
function teamLines(agents: AgentState[], escalations: number): { role: string; text: string }[] {
  const order = ["vp", "director", "manager", "operator", "auditor"];
  const byLevel = new Map<string, AgentState[]>();
  for (const a of agents) byLevel.set(a.node.level, [...(byLevel.get(a.node.level) ?? []), a]);
  return [...byLevel.entries()]
    .sort(([a], [b]) => order.indexOf(a) - order.indexOf(b))
    .map(([level, list]) => {
      const models = [...new Set(list.map((a) => a.node.model))].join(", ");
      const role = `${list.length} ${(LEVEL_WORDS[level] ?? level).toLowerCase()}${list.length === 1 ? "" : "s"}`;
      if (level !== "operator") return { role, text: models };
      const count = (s: string) => list.filter((a) => a.status === s).length;
      const parts = [
        count("done") && `${count("done")} done`,
        count("failed") && `${count("failed")} failed`,
        count("stopped") && `${count("stopped")} stopped on budget`,
        count("working") && `${count("working")} working`,
      ].filter(Boolean);
      if (escalations > 0) parts.push(`${escalations} ${escalations === 1 ? "escalation" : "escalations"}`);
      return { role, text: parts.length ? `${models}. Outcome: ${parts.join(", ")}.` : models };
    });
}

/**
 * The status line under the title: team, budget and run status as three
 * columns of text. Not a floating card; it scrolls with the document.
 */
export function RunHeader({
  status,
  budget,
  decisionNeeded,
  agents,
  escalations,
}: {
  status: string;
  budget: HeaderBudget;
  decisionNeeded: boolean;
  agents: AgentState[];
  escalations: number;
}) {
  const { spent, held, cap, stopped } = budget;
  const over = spent !== null && cap !== null && spent > cap;
  const lines = teamLines(agents, escalations);
  const tone = statusTone(status);
  return (
    <section
      aria-label="Run status"
      className="ui mx-auto mt-34 grid max-w-[1100px] gap-21 border-y border-rule py-21 md:grid-cols-3"
    >
      <div className="min-w-0">
        <Label>Team</Label>
        {lines.length === 0 ? (
          <p className="mt-8 text-muted">No agent has joined yet.</p>
        ) : (
          <ul className="mt-8 flex flex-col gap-8">
            {lines.map((l) => (
              <li key={l.role} className="wrap-anywhere">
                <span className="text-fg">{l.role}</span> <span className="text-muted">{l.text}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="min-w-0">
        <Label>Budget</Label>
        <dl className="mt-8 grid grid-cols-[auto_1fr] gap-x-13">
          <dt className="text-muted">Spent</dt>
          <dd className="num text-cost">{spent === null ? "Not started" : formatMicros(spent)}</dd>
          <dt className="text-muted">Cap</dt>
          <dd className="num">{cap === null ? "Not recorded" : formatMicros(cap)}</dd>
          {held !== null && held > 0n && (
            <>
              <dt className="text-muted">Reserved</dt>
              <dd className="num">{formatMicros(held)}</dd>
            </>
          )}
        </dl>
        <div className="mt-8">
          <Meter spent={spent} held={held} cap={cap} stopped={stopped} />
        </div>
        {over && spent !== null && cap !== null && (
          <p className="mt-8 text-withdrawn">Over the cap by {formatMicros(spent - cap)}.</p>
        )}
      </div>
      <div className="min-w-0">
        <Label>Status</Label>
        <p
          className={`mt-8 font-semibold ${
            tone === "ok" ? "text-supported" : tone === "danger" ? "text-withdrawn" : "text-fg"
          }`}
        >
          <span aria-hidden="true" className="mr-8">
            {tone === "ok" ? "✓" : tone === "danger" ? "✕" : "·"}
          </span>
          {status}
        </p>
        {decisionNeeded && (
          <a href="#decision" onClick={jumpTo("decision")} className="mt-8 inline-block text-fg underline">
            Decision needed: approve or reject
          </a>
        )}
      </div>
    </section>
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
    <div className="ui mx-auto flex max-w-[1100px] flex-wrap items-center justify-center gap-13 px-21 pt-21">
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
      <div role="radiogroup" aria-label="Replay speed" className="flex rounded-sm border border-rule-strong">
        {SPEEDS.map((s) => (
          <button
            key={s}
            type="button"
            role="radio"
            aria-checked={speed === s}
            onClick={() => replay.setSpeed(s)}
            className={`inline-flex min-h-11 min-w-11 items-center justify-center px-13 font-semibold ${
              speed === s ? "bg-fg text-bg" : "text-fg hover:bg-subtle"
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
