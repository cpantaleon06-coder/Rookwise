import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectiveDelay, MAX_DELAY_MS, prepareEvents, Replayer, totalDuration } from "./replay";
import type { RunEvent, TimedEvent } from "./types";

const DEMO = resolve(__dirname, "../../public/recordings/demo/recorded_run.events.json");

function ev(seq: number, delay: number, type = "tool_called"): TimedEvent {
  return {
    delay_ms: delay,
    event: { id: `run_x:${seq}`, seq, run_id: "run_x", mode: "recorded", ts: "", type, payload: {} } as unknown as RunEvent,
  };
}

describe("effectiveDelay", () => {
  it("caps every wait at 1.5 s", () => {
    expect(MAX_DELAY_MS).toBe(1500);
    expect(effectiveDelay(200, "1x")).toBe(200);
    expect(effectiveDelay(1500, "1x")).toBe(1500);
    expect(effectiveDelay(90_000, "1x")).toBe(1500);
  });

  it("divides the capped wait by four at 4x", () => {
    expect(effectiveDelay(200, "4x")).toBe(50);
    expect(effectiveDelay(90_000, "4x")).toBe(375);
  });

  it("waits nothing when instant, and never negative", () => {
    expect(effectiveDelay(1200, "instant")).toBe(0);
    expect(effectiveDelay(-5, "1x")).toBe(0);
    expect(effectiveDelay(Number.NaN, "1x")).toBe(0);
  });
});

describe("prepareEvents", () => {
  it("sorts by seq and drops repeated ids", () => {
    const out = prepareEvents({ run_id: "run_x", events: [ev(3, 10), ev(1, 0), ev(2, 5), ev(2, 99)] });
    expect(out.map((e) => e.event.seq)).toEqual([1, 2, 3]);
    expect(out[1].delay_ms).toBe(5);
  });

  it("refuses a file that is not a recording", () => {
    expect(() => prepareEvents({})).toThrow(/no events list/);
    expect(() => prepareEvents({ events: [{ delay_ms: 0, event: { seq: 1 } }] })).toThrow(/no type/);
  });

  it("reads the shipped demo stream in order", () => {
    const events = prepareEvents(JSON.parse(readFileSync(DEMO, "utf8")));
    expect(events).toHaveLength(64);
    expect(events[0].event.type).toBe("run_started");
    expect(events.at(-1)!.event.type).toBe("run_finished");
    // The demo's longest wait is 2000 ms; the replay caps it.
    expect(Math.max(...events.map((e) => effectiveDelay(e.delay_ms, "1x")))).toBe(1500);
    expect(totalDuration(events, "instant")).toBe(0);
    expect(totalDuration(events, "4x")).toBe(totalDuration(events, "1x") / 4);
  });
});

describe("Replayer", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  const list = [ev(1, 0), ev(2, 0), ev(3, 1000), ev(4, 5000), ev(5, 0)];

  function record(speed: "1x" | "4x" | "instant" = "1x") {
    const batches: number[][] = [];
    const onDone = vi.fn();
    const r = new Replayer(list, {
      speed,
      onEvents: (b) => batches.push(b.map((e) => e.seq)),
      onDone,
    });
    return { r, batches, onDone };
  }

  it("emits zero-delay events at once and waits the capped delay at 1x", () => {
    const { r, batches, onDone } = record("1x");
    r.play();
    expect(batches).toEqual([[1, 2]]);
    vi.advanceTimersByTime(999);
    expect(batches).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(batches).toEqual([[1, 2], [3]]);
    // 5000 ms is capped to 1500 ms; event 5 has no delay and comes in the same batch.
    vi.advanceTimersByTime(1499);
    expect(batches).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(batches).toEqual([[1, 2], [3], [4, 5]]);
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(r.isDone).toBe(true);
    expect(r.isPlaying).toBe(false);
  });

  it("plays four times faster at 4x", () => {
    const { r, batches } = record("4x");
    r.play();
    vi.advanceTimersByTime(250);
    expect(batches).toEqual([[1, 2], [3]]);
    vi.advanceTimersByTime(375);
    expect(batches).toEqual([[1, 2], [3], [4, 5]]);
  });

  it("emits everything in one batch when instant", () => {
    const { r, batches, onDone } = record("instant");
    r.play();
    expect(batches).toEqual([[1, 2, 3, 4, 5]]);
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("pauses and resumes without losing or repeating events", () => {
    const { r, batches } = record("1x");
    r.play();
    r.pause();
    vi.advanceTimersByTime(10_000);
    expect(batches).toEqual([[1, 2]]);
    r.play();
    vi.advanceTimersByTime(1000);
    expect(batches).toEqual([[1, 2], [3]]);
    expect(r.position).toBe(3);
  });

  it("applies a speed change from the next wait on", () => {
    const { r, batches } = record("1x");
    r.play();
    r.setSpeed("4x");
    vi.advanceTimersByTime(250);
    expect(batches).toEqual([[1, 2], [3]]);
    r.setSpeed("instant");
    expect(batches).toEqual([[1, 2], [3], [4, 5]]);
  });

  it("skips to the end and restarts from the first event", () => {
    const { r, batches, onDone } = record("1x");
    r.play();
    r.skipToEnd();
    expect(batches).toEqual([[1, 2], [3, 4, 5]]);
    expect(onDone).toHaveBeenCalledTimes(1);
    r.restart();
    expect(r.position).toBe(0);
    r.play();
    expect(batches.at(-1)).toEqual([1, 2]);
  });

  it("does nothing for an empty list", () => {
    const onEvents = vi.fn();
    const r = new Replayer([], { onEvents });
    r.play();
    expect(onEvents).not.toHaveBeenCalled();
    expect(r.isDone).toBe(true);
  });
});
