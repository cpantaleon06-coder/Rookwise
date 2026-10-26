import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { feedSentence } from "./feed";
import { microsToString, sumMoney } from "./money";
import { prepareEvents } from "./replay";
import { applyEvents, initialRunState, runStatusLabel } from "./runState";

const DEMO = resolve(__dirname, "../../public/recordings/demo/recorded_run.events.json");
const events = prepareEvents(JSON.parse(readFileSync(DEMO, "utf8"))).map((e) => e.event);

describe("applyEvents on the demo recording", () => {
  const final = applyEvents(initialRunState(), events);

  it("ends with the recorded totals, as strings", () => {
    expect(final.budget?.spent).toBe("0.015903");
    expect(final.budget?.cap).toBe("0.250000");
    expect(final.terminal).toMatchObject({ kind: "finished", partial: true, spent: "0.015903" });
    expect(runStatusLabel(final)).toBe("Partial");
  });

  it("takes the totals from the budget_update snapshots, not from summing entries", () => {
    // The synthetic stream sends 11 budget_update events for the 12 ledger entries
    // (t-1's first charge has no event of its own), so the entries seen in the
    // stream add up to less than the absolute total each event carries.
    expect(final.ledger).toHaveLength(11);
    expect(microsToString(sumMoney(final.ledger.map((e) => e.usd_real)))).toBe("0.015839");
    expect(final.budget?.spent).toBe("0.015903");
  });

  it("builds the team, tasks, stops and escalations", () => {
    expect(final.agentOrder).toHaveLength(7);
    expect(final.taskOrder).toEqual(["t-1", "t-2", "t-3", "t-3.2"]);
    expect(final.tasks.get("t-2")?.attempts).toHaveLength(4);
    expect(final.tasks.get("t-2")?.label).toBe("ok_after_escalation");
    expect(final.stops).toHaveLength(1);
    expect(final.agents.get(final.stops[0].agent_id)?.status).toBe("stopped");
    expect(final.escalations).toHaveLength(1);
    expect(final.messages).toHaveLength(3);
    expect(final.audit?.verdict).toBe("accepted");
  });

  it("gives the same state whether events come one by one or all at once", () => {
    let step = initialRunState();
    for (const e of events) step = applyEvents(step, [e]);
    expect(step.budget).toEqual(final.budget);
    expect(step.applied.map((e) => e.id)).toEqual(final.applied.map((e) => e.id));
  });

  it("ignores an event it has already applied", () => {
    const again = applyEvents(final, events.slice(10, 20));
    expect(again).toBe(final);
    expect(again.ledger).toHaveLength(11);
  });

  it("reads Not started before any event", () => {
    expect(runStatusLabel(initialRunState())).toBe("Not started");
  });

  it("writes a feed sentence for every event with money as six decimals", () => {
    for (const e of events) expect(feedSentence(e, final.agents).length).toBeGreaterThan(0);
    const charge = events.find((e) => e.type === "budget_update")!;
    expect(feedSentence(charge, final.agents)).toBe("Charged $0.004800 (director, plan).");
  });
});
