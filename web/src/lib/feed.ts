// One sentence per event for the feed (web/DESIGN.md 3.2.6).

import { formatUsd } from "./money";
import type { AgentState } from "./runState";
import { LEVEL_WORDS, TASK_LABEL_WORDS, VERDICT_WORDS } from "./labels";
import type { RunEvent } from "./types";

export type FeedGroup = "team" | "tasks" | "budget" | "messages" | "audit" | "run";

export const FEED_FILTERS: { id: FeedGroup | "all"; label: string }[] = [
  { id: "all", label: "All" },
  { id: "team", label: "Team" },
  { id: "tasks", label: "Tasks" },
  { id: "budget", label: "Budget" },
  { id: "messages", label: "Messages" },
  { id: "audit", label: "Audit" },
];

export function feedGroup(event: RunEvent): FeedGroup {
  switch (event.type) {
    case "agent_hired":
    case "escalation":
      return "team";
    case "task_assigned":
    case "task_started":
    case "attempt_recorded":
    case "tool_called":
    case "task_result":
      return "tasks";
    case "budget_update":
    case "budget_allocation":
    case "budget_exhausted":
      return "budget";
    case "message":
      return "messages";
    case "audit_result":
      return "audit";
    default:
      return "run";
  }
}

export function agentName(agents: Map<string, AgentState>, id: string | null | undefined): string {
  if (!id) return "Unknown agent";
  const agent = agents.get(id);
  if (!agent) return id;
  const { level, role } = agent.node;
  if (level === "operator") return role;
  return LEVEL_WORDS[level] ?? role;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

export function feedSentence(event: RunEvent, agents: Map<string, AgentState>): string {
  switch (event.type) {
    case "run_started":
      return `Run started with a cap of ${formatUsd(event.payload.budget_usd)}.`;
    case "mode_notice":
      return event.payload.detail || `Notice: ${event.payload.notice}.`;
    case "agent_hired": {
      const a = event.payload.agent;
      const who = a.level === "operator" ? `Operator ${a.role}` : (LEVEL_WORDS[a.level] ?? a.role);
      return `${who} joined (${a.model}).`;
    }
    case "task_assigned":
      return `Task ${event.payload.task.task_id} to ${agentName(agents, event.payload.agent_id)}.`;
    case "task_started":
      return `Attempt ${event.payload.attempt_index + 1} on ${event.payload.model} (task ${event.payload.task_id}).`;
    case "attempt_recorded": {
      const a = event.payload.attempt;
      if (a.ok) return `Attempt ${a.attempt_index + 1} on task ${a.task_id} passed validation.`;
      const n = a.validation_errors.length;
      return `Attempt ${a.attempt_index + 1} on task ${a.task_id} failed${n ? ` validation (${plural(n, "error")})` : ` (${a.loop_status})`}.`;
    }
    case "tool_called":
      return `Tool ${event.payload.tool} ran (${event.payload.ok ? "ok" : (event.payload.error_type ?? "error")}).`;
    case "budget_update": {
      const e = event.payload.entry;
      if (!e) return `Budget now ${formatUsd(event.payload.spent_usd)} spent.`;
      const level = LEVEL_WORDS[e.level] ?? e.level;
      return `Charged ${formatUsd(e.usd_real)} (${level.toLowerCase()}, ${e.task_id})${e.usage_estimated ? ", usage estimated" : ""}.`;
    }
    case "budget_allocation": {
      const p = event.payload;
      const who = agentName(agents, p.agent_id);
      const parent = agentName(agents, p.parent_agent_id);
      return p.action === "allocated"
        ? `Held ${formatUsd(p.usd)} for ${who}.`
        : `Released ${formatUsd(p.usd)} from ${who} back to ${parent}.`;
    }
    case "budget_exhausted":
      return `${agentName(agents, event.payload.agent_id)} stopped: it needed ${formatUsd(event.payload.requested_usd)} and its ${event.payload.scope} cap is ${formatUsd(event.payload.cap_usd)}.`;
    case "message":
      return `${event.payload.message.sender === "user" ? "The user" : capitalize(event.payload.message.sender)} wrote in the chat.`;
    case "task_result": {
      const label = TASK_LABEL_WORDS[event.payload.label] ?? event.payload.label;
      return `Task ${event.payload.result.task_id} ${event.payload.result.status === "ok" ? "done" : "failed"} (${label.toLowerCase()}).`;
    }
    case "escalation":
      return event.payload.reason;
    case "audit_result":
      return `Auditor: ${(VERDICT_WORDS[event.payload.audit.verdict] ?? event.payload.audit.verdict).toLowerCase()}.`;
    case "run_finished":
      return `Run ${event.payload.status}${event.payload.partial ? " (partial)" : ""}. Spent ${formatUsd(event.payload.spent_usd)}.`;
    case "run_failed":
      return `Run failed (${event.payload.error.code}): ${event.payload.error.message} Spent ${formatUsd(event.payload.spent_usd)}.`;
    default:
      return `Event ${(event as { type: string }).type}.`;
  }
}

function capitalize(text: string): string {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}
