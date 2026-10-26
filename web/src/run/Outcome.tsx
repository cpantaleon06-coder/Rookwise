import { Chip, Label, Panel } from "../components/ui";
import { formatMicros, toMicros } from "../lib/money";
import type { RunState } from "../lib/runState";
import type { ChatMessage, DeliveryPackage } from "../lib/types";
import { agentName } from "../lib/feed";

export function PackagePanel({ pkg, partial }: { pkg: DeliveryPackage; partial: boolean }) {
  return (
    <Panel id="package" title="Delivery package" aside={partial ? <Chip tone="danger">Partial</Chip> : undefined}>
      <Label>Summary</Label>
      <p className="mt-1 wrap-anywhere">{pkg.summary || "No summary recorded."}</p>
      {pkg.deliverables.length > 0 && (
        <div className="mt-4">
          <Label>Deliverables</Label>
          <ul className="mt-2 flex flex-col gap-2">
            {pkg.deliverables.map((d) => (
              <li key={`${d.task_id}-${d.title}`} className="min-w-0 rounded-[10px] border border-line p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold wrap-anywhere">{d.title}</span>
                  {partial && <Chip tone="danger">Partial</Chip>}
                </div>
                <pre className="quote mt-2 rounded-[6px] bg-raised p-3">
                  {typeof d.content === "string" ? d.content : JSON.stringify(d.content, null, 2)}
                </pre>
              </li>
            ))}
          </ul>
        </div>
      )}
      {pkg.decisions.length > 0 && (
        <div className="mt-4">
          <Label>Decisions the run recorded</Label>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
            {pkg.decisions.map((d, i) => (
              <li key={i} className="wrap-anywhere">{d}</li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}

export function StopBanner({ state }: { state: RunState }) {
  if (state.stops.length === 0) return null;
  const first = state.stops.slice(0, 3);
  const partial = state.terminal ? state.terminal.partial : null;
  return (
    <div role="region" aria-label="Budget stops" className="rounded-[16px] border-l-4 border-danger bg-danger-tint p-4 sm:p-6">
      <p className="label text-danger">Stopped on budget</p>
      <p className="mt-1 font-semibold">
        {state.stops.length === 1
          ? "One agent stopped on its budget."
          : `${state.stops.length} agents stopped on their budget.`}
        {partial ? " The result below is partial." : ""}
      </p>
      <ul className="mt-2 flex flex-col gap-1 text-sm">
        {first.map((s, i) => {
          const left = toMicros(s.cap_usd) - toMicros(s.committed_usd);
          return (
            <li key={i} className="wrap-anywhere">
              {agentName(state.agents, s.agent_id)} needed {formatMicros(toMicros(s.requested_usd))} and had{" "}
              {formatMicros(left < 0n ? 0n : left)} left.
            </li>
          );
        })}
      </ul>
      {state.stops.length > first.length && (
        <p className="mt-1 text-sm text-muted">And {state.stops.length - first.length} more, listed in the budget panel.</p>
      )}
    </div>
  );
}

export function TerminalBanner({ state }: { state: RunState }) {
  const t = state.terminal;
  if (!t) return null;
  if (t.kind === "failed") {
    return (
      <div role="region" aria-label="Run failed" className="rounded-[16px] border-l-4 border-danger bg-danger-tint p-4 sm:p-6">
        <p className="label text-danger">Run failed: {t.code}</p>
        <p className="mt-1 wrap-anywhere">{t.message}</p>
        <p className="mt-1 text-sm">Spent {formatMicros(toMicros(t.spent))}.</p>
      </div>
    );
  }
  if (t.status === "cancelled") {
    return (
      <div className="rounded-[16px] border-l-4 border-danger bg-danger-tint p-4 sm:p-6">
        <p className="font-semibold">The run was cancelled. Spent {formatMicros(toMicros(t.spent))}.</p>
      </div>
    );
  }
  return null;
}

export function ChatPanel({ messages }: { messages: ChatMessage[] }) {
  return (
    <Panel id="chat" title="Chat with the director">
      {messages.length === 0 ? (
        <p className="text-muted">No message yet.</p>
      ) : (
        <ol className="flex flex-col gap-2">
          {messages.map((m) => (
            <li
              key={m.message_id}
              className={`min-w-0 max-w-[90%] rounded-[10px] p-3 text-sm ${
                m.sender === "user" ? "self-end bg-raised" : "self-start border border-line"
              }`}
            >
              <Label>{m.sender}</Label>
              <p className="mt-1 wrap-anywhere whitespace-pre-wrap">{m.text}</p>
            </li>
          ))}
        </ol>
      )}
      <form className="mt-4 flex flex-col gap-2" onSubmit={(e) => e.preventDefault()}>
        <label htmlFor="chat-input" className="label text-muted">
          Message
        </label>
        <textarea
          id="chat-input"
          disabled
          aria-describedby="chat-note"
          rows={2}
          className="w-full resize-none rounded-[6px] border border-line bg-raised p-2 text-sm text-muted"
        />
        <p id="chat-note" className="text-sm text-muted">
          Recorded run: you can read the chat but not write in it.
        </p>
      </form>
    </Panel>
  );
}
