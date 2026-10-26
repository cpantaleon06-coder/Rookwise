// The run as the replay has shown it so far. `applyEvents` is a pure reducer:
// every payload is a full snapshot of what it describes (docs/api.md, "Ordering
// and idempotency"), and an event already applied (same id) is ignored.

import { toMicros, toMicrosOrNull, type Micros } from "./money";
import type {
  AgentNode,
  AgentStatus,
  AttemptRecord,
  AuditVerdict,
  BudgetExhaustedEvent,
  ChatMessage,
  EscalationEvent,
  LedgerEntry,
  RunEvent,
  TaskV1,
} from "./types";

export type TaskStatus = "assigned" | "running" | "ok" | "failed";

export interface TaskState {
  task: TaskV1;
  agentId: string;
  operatorId: string | null;
  status: TaskStatus;
  label: string | null;
  attempts: AttemptRecord[];
  spent: Micros;
}

export interface AgentState {
  node: AgentNode;
  status: AgentStatus | "stopped";
  allocated: Micros | null;
  released: Micros | null;
  spent: Micros;
}

export interface Budget {
  spent: string;
  held: string;
  predicted: string;
  cap: string;
  spentByLevel: Record<string, string>;
}

export type Terminal =
  | { kind: "finished"; status: string; partial: boolean; spent: string; predicted: string }
  | { kind: "failed"; code: string; message: string; partial: boolean; spent: string };

export interface RunState {
  seen: Set<string>;
  applied: RunEvent[];
  started: boolean;
  goal: string | null;
  cap: string | null;
  simulatedCase: boolean | null;
  modeNotice: string | null;
  agents: Map<string, AgentState>;
  agentOrder: string[];
  tasks: Map<string, TaskState>;
  taskOrder: string[];
  budget: Budget | null;
  ledger: LedgerEntry[];
  stops: BudgetExhaustedEvent["payload"][];
  escalations: EscalationEvent["payload"][];
  messages: ChatMessage[];
  audit: AuditVerdict | null;
  terminal: Terminal | null;
  toolCalls: number;
}

export function initialRunState(): RunState {
  return {
    seen: new Set(),
    applied: [],
    started: false,
    goal: null,
    cap: null,
    simulatedCase: null,
    modeNotice: null,
    agents: new Map(),
    agentOrder: [],
    tasks: new Map(),
    taskOrder: [],
    budget: null,
    ledger: [],
    stops: [],
    escalations: [],
    messages: [],
    audit: null,
    terminal: null,
    toolCalls: 0,
  };
}

function eventId(event: RunEvent): string {
  return typeof event.id === "string" ? event.id : `${event.run_id}:${event.seq}`;
}

function money(value: string): Micros {
  return toMicrosOrNull(value) ?? 0n;
}

/** Apply events in order. Returns a new state object; maps are copied on write. */
export function applyEvents(previous: RunState, events: readonly RunEvent[]): RunState {
  const fresh = events.filter((e) => !previous.seen.has(eventId(e)));
  if (fresh.length === 0) return previous;

  const s: RunState = {
    ...previous,
    seen: new Set(previous.seen),
    applied: [...previous.applied],
    agents: new Map(previous.agents),
    agentOrder: [...previous.agentOrder],
    tasks: new Map(previous.tasks),
    taskOrder: [...previous.taskOrder],
    ledger: [...previous.ledger],
    stops: [...previous.stops],
    escalations: [...previous.escalations],
    messages: [...previous.messages],
  };

  const updateAgent = (id: string, change: (a: AgentState) => AgentState) => {
    const current = s.agents.get(id);
    if (current) s.agents.set(id, change(current));
  };
  const updateTask = (id: string, change: (t: TaskState) => TaskState) => {
    const current = s.tasks.get(id);
    if (current) s.tasks.set(id, change(current));
  };

  for (const event of fresh) {
    const id = eventId(event);
    if (s.seen.has(id)) continue;
    s.seen.add(id);
    s.applied.push(event);

    switch (event.type) {
      case "run_started":
        s.started = true;
        s.goal = event.payload.goal;
        s.cap = event.payload.budget_usd;
        s.simulatedCase = event.payload.simulated_case;
        break;
      case "mode_notice":
        s.modeNotice = event.payload.detail || null;
        break;
      case "agent_hired": {
        const node = event.payload.agent;
        if (!s.agents.has(node.agent_id)) s.agentOrder.push(node.agent_id);
        const prior = s.agents.get(node.agent_id);
        s.agents.set(node.agent_id, {
          node,
          status: node.status,
          allocated: prior?.allocated ?? null,
          released: prior?.released ?? null,
          spent: prior?.spent ?? 0n,
        });
        break;
      }
      case "task_assigned": {
        const { task, agent_id, operator_id } = event.payload;
        if (!s.tasks.has(task.task_id)) s.taskOrder.push(task.task_id);
        s.tasks.set(task.task_id, {
          task,
          agentId: agent_id,
          operatorId: operator_id,
          status: "assigned",
          label: null,
          attempts: [],
          spent: s.tasks.get(task.task_id)?.spent ?? 0n,
        });
        break;
      }
      case "task_started":
        updateTask(event.payload.task_id, (t) => ({ ...t, status: "running" }));
        // Only operator status follows from events; other levels have no status events (M11).
        updateAgent(event.payload.agent_id, (a) =>
          a.node.level === "operator" && a.status !== "stopped" ? { ...a, status: "working" } : a,
        );
        break;
      case "attempt_recorded": {
        const attempt = event.payload.attempt;
        updateTask(attempt.task_id, (t) => ({
          ...t,
          attempts: [
            ...t.attempts.filter((x) => x.attempt_index !== attempt.attempt_index),
            attempt,
          ],
        }));
        break;
      }
      case "tool_called":
        s.toolCalls += 1;
        break;
      case "budget_update": {
        const p = event.payload;
        s.budget = {
          spent: p.spent_usd,
          held: p.held_usd,
          predicted: p.predicted_usd,
          cap: p.cap_usd,
          spentByLevel: { ...p.spent_by_level },
        };
        const entry = p.entry;
        if (entry) {
          s.ledger.push(entry);
          // Spend per agent is known for operator tasks only (LedgerEntry has no agent_id).
          const task = s.tasks.get(entry.task_id);
          if (task && entry.level === "operator") {
            const usd = money(entry.usd_real);
            updateTask(entry.task_id, (t) => ({ ...t, spent: t.spent + usd }));
            updateAgent(task.agentId, (a) => ({ ...a, spent: a.spent + usd }));
          }
        }
        break;
      }
      case "budget_allocation": {
        const p = event.payload;
        const usd = money(p.usd);
        updateAgent(p.agent_id, (a) =>
          p.action === "allocated"
            ? { ...a, allocated: (a.allocated ?? 0n) + usd }
            : { ...a, released: (a.released ?? 0n) + usd },
        );
        break;
      }
      case "budget_exhausted":
        s.stops.push(event.payload);
        updateAgent(event.payload.agent_id, (a) => ({ ...a, status: "stopped" }));
        break;
      case "message":
        if (!s.messages.some((m) => m.message_id === event.payload.message.message_id)) {
          s.messages.push(event.payload.message);
        }
        break;
      case "task_result": {
        const { result, label, agent_id } = event.payload;
        updateTask(result.task_id, (t) => ({ ...t, status: result.status, label }));
        updateAgent(agent_id, (a) =>
          a.status === "stopped" || a.node.level !== "operator"
            ? a
            : { ...a, status: result.status === "ok" ? "done" : "failed" },
        );
        break;
      }
      case "escalation":
        s.escalations.push(event.payload);
        break;
      case "audit_result":
        s.audit = event.payload.audit;
        break;
      case "run_finished":
        s.terminal = {
          kind: "finished",
          status: event.payload.status,
          partial: event.payload.partial,
          spent: event.payload.spent_usd,
          predicted: event.payload.predicted_usd,
        };
        break;
      case "run_failed":
        s.terminal = {
          kind: "failed",
          code: event.payload.error.code,
          message: event.payload.error.message,
          partial: event.payload.partial,
          spent: event.payload.spent_usd,
        };
        break;
      default:
        // Unknown event types are kept in `applied` (the feed shows them) and change nothing else.
        break;
    }
  }
  return s;
}

/** Status words for the run header (web/DESIGN.md 3.2.1). */
export function runStatusLabel(state: RunState): string {
  const t = state.terminal;
  if (t) {
    if (t.kind === "failed") return "Failed";
    if (t.status === "cancelled") return "Cancelled";
    return t.partial ? "Partial" : "Finished";
  }
  if (!state.started) return "Not started";
  return state.taskOrder.length === 0 ? "Planning" : "Running";
}

/** Spent, held and cap in micro-USD, with the cap taken from the first place that has it. */
export function budgetMicros(state: RunState, fallbackCap: string | null) {
  const cap = state.budget?.cap ?? state.cap ?? fallbackCap;
  return {
    spent: state.budget ? toMicros(state.budget.spent) : null,
    held: state.budget ? toMicros(state.budget.held) : null,
    predicted: state.budget ? toMicros(state.budget.predicted) : null,
    cap: cap ? toMicrosOrNull(cap) : null,
  };
}
