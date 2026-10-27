import { useEffect, useRef, useState } from "react";
import { Label, Panel } from "../components/ui";
import { agentName, FEED_FILTERS, feedGroup, feedSentence, type FeedGroup } from "../lib/feed";
import { elapsed } from "../lib/labels";
import type { RunState } from "../lib/runState";
import type { RunEvent } from "../lib/types";

function actorOf(event: RunEvent, state: RunState): string {
  const p = event.payload as Record<string, unknown>;
  if (event.type === "agent_hired") return agentName(state.agents, event.payload.agent.agent_id);
  if (event.type === "message") return event.payload.message.sender === "user" ? "User" : "Director";
  if (event.type === "audit_result") return "Auditor";
  if (event.type === "budget_update" || event.type === "budget_allocation") return "Ledger";
  if (typeof p.agent_id === "string") return agentName(state.agents, p.agent_id);
  if (typeof p.from_agent_id === "string") return agentName(state.agents, p.from_agent_id);
  return "Run";
}

export function FeedPanel({ state, done }: { state: RunState; done: boolean }) {
  const [filter, setFilter] = useState<FeedGroup | "all">("all");
  const [follow, setFollow] = useState(true);
  const [announce, setAnnounce] = useState(false);
  const listRef = useRef<HTMLOListElement>(null);
  const start = state.applied.find((e) => e.type === "run_started")?.ts ?? state.applied[0]?.ts ?? null;
  const rows = state.applied.filter((e) => filter === "all" || feedGroup(e) === filter);

  useEffect(() => {
    const list = listRef.current;
    if (follow && list) list.scrollTop = list.scrollHeight;
  }, [rows.length, follow]);

  return (
    <Panel id="feed" title="Feed" aside={<Label>{state.applied.length} events</Label>}>
      <div className="flex flex-wrap items-center gap-8" role="radiogroup" aria-label="Filter the feed">
        {FEED_FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            role="radio"
            aria-checked={filter === f.id}
            onClick={() => setFilter(f.id)}
            className={`label inline-flex min-h-11 items-center rounded-full px-13 ${
              filter === f.id ? "bg-bone text-ink" : "border border-line-strong hover:bg-raised"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>
      <div className="mt-13 flex flex-wrap gap-x-21 gap-y-8">
        <label className="inline-flex min-h-11 items-center gap-8">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} className="size-4" />
          Follow the newest event
        </label>
        <label className="inline-flex min-h-11 items-center gap-8">
          <input type="checkbox" checked={announce} onChange={(e) => setAnnounce(e.target.checked)} className="size-4" />
          Announce feed events
        </label>
      </div>
      <ol
        ref={listRef}
        role="log"
        aria-live={announce ? "polite" : "off"}
        aria-label="Run events"
        tabIndex={0}
        className="mt-13 max-h-[28rem] overflow-y-auto rounded-md border border-line"
      >
        {rows.length === 0 && <li className="p-13 text-muted">No event to show yet.</li>}
        {rows.map((event) => {
          const terminal = event.type === "run_finished" || event.type === "run_failed";
          const stop = event.type === "budget_exhausted";
          return (
            <li
              key={event.id}
              className={`grid grid-cols-[4.5rem_1fr] gap-8 border-b border-line px-13 py-8 last:border-b-0 ${
                terminal || stop ? (event.type === "run_failed" || stop ? "bg-berry-tint" : "bg-raised") : ""
              }`}
            >
              <span className="figure text-muted">{elapsed(start, event.ts)}</span>
              <span className="min-w-0 wrap-anywhere">
                <span className="font-medium">{actorOf(event, state)}</span>{" "}
                <span className="text-muted">{feedSentence(event, state.agents)}</span>
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-8 text-muted">{done ? "Run ended." : "Replaying."}</p>
    </Panel>
  );
}
