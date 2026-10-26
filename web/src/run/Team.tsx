import { Chip, Label, Panel, type Tone } from "../components/ui";
import { agentName } from "../lib/feed";
import { AGENT_STATUS_WORDS, ATTEMPT_REASON_WORDS, LEVEL_WORDS, TASK_LABEL_WORDS } from "../lib/labels";
import { formatMicros } from "../lib/money";
import type { AgentState, RunState, TaskState } from "../lib/runState";
import type { AgentNode } from "../lib/types";

const STATUS_TONE: Record<string, Tone> = {
  hired: "neutral",
  working: "neutral",
  idle: "neutral",
  done: "ok",
  failed: "danger",
  stopped: "danger",
};

function AgentLine({ agent }: { agent: AgentState }) {
  const n = agent.node;
  const status = agent.status;
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 py-2">
      <span className="font-medium wrap-anywhere">
        {n.level === "operator" ? n.role : (LEVEL_WORDS[n.level] ?? n.role)}
      </span>
      <Label>{LEVEL_WORDS[n.level] ?? n.level}</Label>
      <span className="num wrap-anywhere text-xs text-muted">{n.model}</span>
      <Chip tone={STATUS_TONE[status] ?? "neutral"}>{AGENT_STATUS_WORDS[status] ?? status}</Chip>
      {agent.allocated !== null && (
        <span className="num text-xs text-muted">held {formatMicros(agent.allocated)}</span>
      )}
      {n.level === "operator" && agent.spent > 0n && (
        <span className="num text-xs text-muted">spent {formatMicros(agent.spent)}</span>
      )}
    </div>
  );
}

function statusCounts(agents: AgentState[]): string {
  const counts = new Map<string, number>();
  for (const a of agents) {
    const word = (AGENT_STATUS_WORDS[a.status] ?? a.status).toLowerCase();
    counts.set(word, (counts.get(word) ?? 0) + 1);
  }
  return [...counts.entries()].map(([w, n]) => `${n} ${w}`).join(", ");
}

/** Indented list (web/DESIGN.md 3.2.5), indentation capped at 3 levels. */
function Branch({
  id,
  tree,
  state,
  depth,
}: {
  id: string;
  tree: Map<string, string[]>;
  state: RunState;
  depth: number;
}) {
  const agent = state.agents.get(id);
  if (!agent) return null;
  const kids = (tree.get(id) ?? []).map((k) => state.agents.get(k)!).filter(Boolean);
  const operators = kids.filter((k) => k.node.level === "operator");
  const others = kids.filter((k) => k.node.level !== "operator");
  const indent = depth > 0 && depth <= 3 ? "pl-3 border-l border-line ml-1" : "";
  return (
    <li className={`min-w-0 ${indent}`}>
      <AgentLine agent={agent} />
      {others.length > 0 && (
        <ul>
          {others.map((k) => (
            <Branch key={k.node.agent_id} id={k.node.agent_id} tree={tree} state={state} depth={depth + 1} />
          ))}
        </ul>
      )}
      {operators.length > 0 && (
        <details open={operators.length <= 6} className="ml-1 border-l border-line pl-3">
          <summary className="min-h-11 cursor-pointer py-2 text-sm text-muted">
            {operators.length} {operators.length === 1 ? "operator" : "operators"}: {statusCounts(operators)}
          </summary>
          <ul>
            {operators.map((k) => (
              <Branch key={k.node.agent_id} id={k.node.agent_id} tree={tree} state={state} depth={4} />
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}

function withFinalStatuses(state: RunState, snapshot: AgentNode[]): RunState {
  const final = new Map(snapshot.map((n) => [n.agent_id, n.status]));
  const agents = new Map(state.agents);
  for (const [id, a] of agents) {
    const s = final.get(id);
    if (s && a.status !== "stopped") agents.set(id, { ...a, status: s });
  }
  return { ...state, agents };
}

/**
 * `snapshot` is the org chart the recording kept at the end of the run; once
 * the replay reached the end, its statuses replace the ones derived from events
 * (except a budget stop, which the snapshot does not name).
 */
export function TeamPanel({ state: live, snapshot }: { state: RunState; snapshot: AgentNode[] | null }) {
  const state = snapshot ? withFinalStatuses(live, snapshot) : live;
  const tree = new Map<string, string[]>();
  const roots: string[] = [];
  for (const id of state.agentOrder) {
    const parent = state.agents.get(id)!.node.parent_id;
    if (parent && state.agents.has(parent)) {
      tree.set(parent, [...(tree.get(parent) ?? []), id]);
    } else {
      roots.push(id);
    }
  }
  return (
    <Panel id="team" title="Team" aside={<Label>{state.agentOrder.length} agents</Label>}>
      {roots.length === 0 ? (
        <p className="text-muted">No agent has joined yet.</p>
      ) : (
        <ul aria-label="Org chart">
          {roots.map((id) => (
            <Branch key={id} id={id} tree={tree} state={state} depth={0} />
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-muted">
        Spend per agent is shown for operators only: ledger entries name a task, not an agent.
      </p>
      {state.escalations.length > 0 && (
        <div className="mt-4 border-t border-line pt-4">
          <h3 className="mb-2 font-semibold">Reassignments and escalations ({state.escalations.length})</h3>
          <ul className="flex flex-col gap-2 text-sm">
            {state.escalations.map((e, i) => (
              <li key={i} className="min-w-0 rounded-[10px] border border-line p-3">
                <p className="wrap-anywhere">
                  <span className="font-medium">{agentName(state.agents, e.from_agent_id)}</span>
                  <span aria-hidden="true"> → </span>
                  <span className="sr-only"> to </span>
                  <span className="font-medium">{agentName(state.agents, e.to_agent_id)}</span>
                  {e.task_id && <span className="num text-muted"> (task {e.task_id})</span>}
                </p>
                <p className="mt-1 wrap-anywhere text-muted">{e.reason}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}

function taskTone(t: TaskState): Tone {
  if (t.status === "ok") return "ok";
  if (t.status === "failed") return "danger";
  return "neutral";
}

const TASK_STATUS_WORDS: Record<string, string> = {
  assigned: "Assigned",
  running: "Running",
  ok: "Done",
  failed: "Failed",
};

export function TaskPanel({ state }: { state: RunState }) {
  const tasks = state.taskOrder.map((id) => state.tasks.get(id)!);
  const done = tasks.filter((t) => t.status === "ok").length;
  const failed = tasks.filter((t) => t.status === "failed").length;
  return (
    <Panel
      id="tasks"
      title="Tasks"
      aside={
        <Label>
          {tasks.length} total, {done} done, {failed} failed
        </Label>
      }
    >
      {tasks.length === 0 ? (
        <p className="text-muted">No task has been assigned yet.</p>
      ) : (
        <ol
          tabIndex={0}
          aria-label="Task list"
          className="flex max-h-[32rem] flex-col gap-2 overflow-y-auto pr-1"
        >
          {tasks.map((t) => {
            const errors = t.attempts.flatMap((a) => a.validation_errors);
            return (
              <li key={t.task.task_id} className="min-w-0 rounded-[10px] border border-line p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="num font-medium">{t.task.task_id}</span>
                  <span className="wrap-anywhere">{t.task.role}</span>
                  <Chip tone={taskTone(t)}>{TASK_STATUS_WORDS[t.status] ?? t.status}</Chip>
                  {t.label && t.label !== "failed" && (
                    <span className="text-muted">{TASK_LABEL_WORDS[t.label] ?? t.label}</span>
                  )}
                </div>
                <p className="mt-1 text-muted">
                  {agentName(state.agents, t.agentId)}
                  {t.attempts.length > 0 &&
                    `; ${t.attempts.length} ${t.attempts.length === 1 ? "attempt" : "attempts"} (${t.attempts
                      .map((a) => ATTEMPT_REASON_WORDS[a.reason] ?? a.reason)
                      .join(", ")})`}
                  {t.spent > 0n && (
                    <>
                      ; spent <span className="num text-ink">{formatMicros(t.spent)}</span>
                    </>
                  )}
                </p>
                {errors.length > 0 && (
                  <details className="mt-1">
                    <summary className="cursor-pointer text-muted">
                      {errors.length} validation {errors.length === 1 ? "error" : "errors"}
                    </summary>
                    <ul className="mt-1 list-disc pl-5">
                      {errors.map((e, i) => (
                        <li key={i} className="quote text-xs">
                          {e}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </Panel>
  );
}
