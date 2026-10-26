import { describe, expect, it, vi } from "vitest";
import { clearDecision, getDecision, recordDecision, subscribe } from "./approval";

describe("approval decisions in memory", () => {
  it("records, replaces and clears a decision per run", () => {
    const listener = vi.fn();
    const unsubscribe = subscribe(listener);
    expect(getDecision("demo:run_1")).toBeNull();

    recordDecision("demo:run_1", "approved", new Date("2026-10-25T12:00:00Z"));
    expect(getDecision("demo:run_1")).toEqual({ choice: "approved", at: "2026-10-25T12:00:00.000Z" });
    expect(getDecision("demo:run_2")).toBeNull();

    recordDecision("demo:run_1", "rejected");
    expect(getDecision("demo:run_1")?.choice).toBe("rejected");

    clearDecision("demo:run_1");
    expect(getDecision("demo:run_1")).toBeNull();
    expect(listener).toHaveBeenCalledTimes(3);

    unsubscribe();
    recordDecision("demo:run_1", "approved");
    expect(listener).toHaveBeenCalledTimes(3);
    clearDecision("demo:run_1");
  });

  it("keeps the same object between reads so React does not re-render for nothing", () => {
    recordDecision("demo:run_3", "approved");
    expect(getDecision("demo:run_3")).toBe(getDecision("demo:run_3"));
    clearDecision("demo:run_3");
  });
});
