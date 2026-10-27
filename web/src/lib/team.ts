// The team of a recording, counted by level and model, for the landing's
// hierarchy figure. Every number comes from the recording's org chart.

import type { AgentNode } from "./types";

export interface ModelCount {
  model: string;
  count: number;
}

export interface TeamLevel {
  level: string;
  count: number;
  models: ModelCount[];
}

export interface TeamSummary {
  levels: TeamLevel[];
  /** The operators' models in the order they joined, one entry per operator. */
  operators: string[];
}

const ORDER = ["vp", "director", "manager", "operator", "auditor"];

export function teamOf(nodes: AgentNode[] | null | undefined): TeamSummary | null {
  if (!Array.isArray(nodes) || nodes.length === 0) return null;
  const byLevel = new Map<string, Map<string, number>>();
  for (const node of nodes) {
    const models = byLevel.get(node.level) ?? new Map<string, number>();
    models.set(node.model, (models.get(node.model) ?? 0) + 1);
    byLevel.set(node.level, models);
  }
  const rank = (level: string) => {
    const i = ORDER.indexOf(level);
    return i < 0 ? ORDER.length : i;
  };
  const levels = [...byLevel.entries()]
    .sort(([a], [b]) => rank(a) - rank(b))
    .map(([level, models]) => {
      const list = [...models.entries()]
        .map(([model, count]) => ({ model, count }))
        .sort((a, b) => b.count - a.count || a.model.localeCompare(b.model));
      return { level, count: list.reduce((n, m) => n + m.count, 0), models: list };
    });
  const operators = nodes.filter((n) => n.level === "operator").map((n) => n.model);
  return { levels, operators };
}
