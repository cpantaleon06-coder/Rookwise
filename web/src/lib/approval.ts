// The approval gate's decision lives in this tab's memory only: no storage, no
// request. Reloading the page forgets it. Rookwise v1 executes nothing either way.

export type Choice = "approved" | "rejected";

export interface Decision {
  choice: Choice;
  at: string;
}

type Listener = () => void;

const decisions = new Map<string, Decision>();
const listeners = new Set<Listener>();

function notify(): void {
  for (const listener of listeners) listener();
}

export function getDecision(key: string): Decision | null {
  return decisions.get(key) ?? null;
}

export function recordDecision(key: string, choice: Choice, now: Date = new Date()): Decision {
  const decision = { choice, at: now.toISOString() };
  decisions.set(key, decision);
  notify();
  return decision;
}

export function clearDecision(key: string): void {
  if (decisions.delete(key)) notify();
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
