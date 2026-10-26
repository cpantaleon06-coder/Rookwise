import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { teamOf } from "./team";
import type { AgentNode } from "./types";

function node(level: AgentNode["level"], model: string, i: number): AgentNode {
  return {
    agent_id: `${level}-${i}`,
    level,
    role: level,
    model,
    operator_id: null,
    parent_id: null,
    skills: [],
    tools: [],
    status: "done",
  };
}

describe("teamOf", () => {
  it("is null without an org chart", () => {
    expect(teamOf(null)).toBeNull();
    expect(teamOf([])).toBeNull();
  });

  it("orders the levels top down and counts each model", () => {
    const team = teamOf([
      node("operator", "small", 1),
      node("auditor", "large", 1),
      node("director", "large", 1),
      node("operator", "small", 2),
      node("operator", "medium", 3),
      node("manager", "medium", 1),
    ])!;
    expect(team.levels.map((l) => l.level)).toEqual(["director", "manager", "operator", "auditor"]);
    expect(team.levels[2]).toEqual({
      level: "operator",
      count: 3,
      models: [
        { model: "small", count: 2 },
        { model: "medium", count: 1 },
      ],
    });
    expect(team.operators).toEqual(["small", "small", "medium"]);
  });

  it("matches the org chart of the inc-03-run2 recording", () => {
    const path = resolve(__dirname, "../../public/recordings/inc-03-run2/recorded_run.json");
    const bundle = JSON.parse(readFileSync(path, "utf8")) as { org: { nodes: AgentNode[] } };
    const team = teamOf(bundle.org.nodes)!;
    const words = team.levels.map((l) => `${l.level}:${l.models.map((m) => `${m.model}=${m.count}`).join(",")}`);
    expect(words).toEqual([
      "director:nemotron-3-ultra=1",
      "manager:nemotron-3-super=5",
      "operator:nemotron-3.5-lightning=60,nemotron-3-super=7",
      "auditor:nemotron-3-ultra=1",
    ]);
  });
});
