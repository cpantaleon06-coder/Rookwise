// Client-side replay of a recorded event stream. A recording is a list of
// {delay_ms, event}; each event waits its own delay (capped) before it is
// applied. Nothing here touches the network or the DOM.

import type { EventsFile, RunEvent, TimedEvent } from "./types.ts";

/** No single wait is longer than this, whatever the recording says. */
export const MAX_DELAY_MS = 1500;

export type Speed = "1x" | "4x" | "instant";

export const SPEEDS: readonly Speed[] = ["1x", "4x", "instant"];

/** The wait before an event at a given speed: capped at MAX_DELAY_MS, then divided. */
export function effectiveDelay(delayMs: number, speed: Speed): number {
  if (speed === "instant") return 0;
  const raw = Number.isFinite(delayMs) ? Math.max(0, delayMs) : 0;
  const capped = Math.min(raw, MAX_DELAY_MS);
  return speed === "4x" ? capped / 4 : capped;
}

/**
 * Validate the events file and put it in replay order: sorted by `seq`,
 * duplicates (same `id`) dropped, keeping the first. Throws on a file that is
 * not a recording.
 */
export function prepareEvents(file: unknown): TimedEvent[] {
  if (!file || typeof file !== "object" || !Array.isArray((file as EventsFile).events)) {
    throw new Error("The events file has no events list.");
  }
  const seen = new Set<string>();
  const out: TimedEvent[] = [];
  for (const item of (file as EventsFile).events) {
    const event = item?.event as RunEvent | undefined;
    if (!event || typeof event.type !== "string" || typeof event.seq !== "number") {
      throw new Error("An event in the events file has no type or seq.");
    }
    const id = typeof event.id === "string" ? event.id : `${event.run_id}:${event.seq}`;
    if (seen.has(id)) continue;
    seen.add(id);
    out.push({ delay_ms: Number(item.delay_ms) || 0, event });
  }
  out.sort((a, b) => a.event.seq - b.event.seq);
  return out;
}

/** Total time a replay takes at a speed, in ms. */
export function totalDuration(events: readonly TimedEvent[], speed: Speed): number {
  return events.reduce((sum, e) => sum + effectiveDelay(e.delay_ms, speed), 0);
}

export interface Scheduler {
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

const defaultScheduler: Scheduler = {
  setTimeout: (fn, ms) => globalThis.setTimeout(fn, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export interface ReplayerOptions {
  /** Called with the events that became due, in order. Zero-delay runs come as one batch. */
  onEvents: (events: RunEvent[]) => void;
  /** Called once when the last event was emitted. */
  onDone?: () => void;
  speed?: Speed;
  scheduler?: Scheduler;
}

/**
 * Plays a prepared event list. `play`, `pause`, `setSpeed` and `restart` can be
 * called at any time. A speed change applies from the next wait on.
 */
export class Replayer {
  private readonly events: readonly TimedEvent[];
  private readonly onEvents: (events: RunEvent[]) => void;
  private readonly onDone?: () => void;
  private readonly scheduler: Scheduler;
  private speedValue: Speed;
  private index = 0;
  private timer: unknown = null;
  private playing = false;

  constructor(events: readonly TimedEvent[], options: ReplayerOptions) {
    this.events = events;
    this.onEvents = options.onEvents;
    this.onDone = options.onDone;
    this.speedValue = options.speed ?? "1x";
    this.scheduler = options.scheduler ?? defaultScheduler;
  }

  get position(): number {
    return this.index;
  }

  get length(): number {
    return this.events.length;
  }

  get speed(): Speed {
    return this.speedValue;
  }

  get isPlaying(): boolean {
    return this.playing;
  }

  get isDone(): boolean {
    return this.index >= this.events.length;
  }

  play(): void {
    if (this.playing || this.isDone) return;
    this.playing = true;
    this.scheduleNext();
  }

  pause(): void {
    this.playing = false;
    this.clearTimer();
  }

  setSpeed(speed: Speed): void {
    this.speedValue = speed;
    if (this.playing) {
      this.clearTimer();
      this.scheduleNext();
    }
  }

  /** Back to the first event. The caller resets its own state. */
  restart(): void {
    this.pause();
    this.index = 0;
  }

  /** Emit everything left at once. */
  skipToEnd(): void {
    this.clearTimer();
    this.flush(this.events.length);
  }

  dispose(): void {
    this.pause();
  }

  private clearTimer(): void {
    if (this.timer !== null) {
      this.scheduler.clearTimeout(this.timer);
      this.timer = null;
    }
  }

  private scheduleNext(): void {
    if (!this.playing) return;
    if (this.isDone) {
      this.playing = false;
      return;
    }
    if (this.speedValue === "instant") {
      this.flush(this.events.length);
      return;
    }
    const wait = effectiveDelay(this.events[this.index].delay_ms, this.speedValue);
    if (wait <= 0) {
      this.emitDue();
      return;
    }
    this.timer = this.scheduler.setTimeout(() => {
      this.timer = null;
      this.emitDue();
    }, wait);
  }

  /** Emit the next event plus every following event whose wait is zero. */
  private emitDue(): void {
    let end = this.index + 1;
    while (
      end < this.events.length &&
      effectiveDelay(this.events[end].delay_ms, this.speedValue) <= 0
    ) {
      end += 1;
    }
    this.flush(end);
    if (this.playing) this.scheduleNext();
  }

  private flush(end: number): void {
    if (end <= this.index) return;
    const batch = this.events.slice(this.index, end).map((e) => e.event);
    this.index = end;
    this.onEvents(batch);
    if (this.isDone) {
      this.playing = false;
      this.onDone?.();
    }
  }
}
