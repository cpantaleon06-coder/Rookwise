import { useSyncExternalStore } from "react";
import { ApproveControls } from "../components/hold";
import { Button, Chip, Label, Panel } from "../components/ui";
import { clearDecision, getDecision, recordDecision, subscribe } from "../lib/approval";
import { formatDate } from "../lib/labels";
import { formatMicros, toMicros } from "../lib/money";
import type { RunState } from "../lib/runState";
import type { ChatMessage, DeliveryPackage } from "../lib/types";
import { agentName } from "../lib/feed";

const NOTHING_RUNS =
  "Rookwise v1 executes nothing. Your choice is recorded in this browser tab only: nothing is sent anywhere and nothing runs on your systems.";

/**
 * The approval gate (task step 3). Shown once the replay reached the end of the
 * run. Approve or Reject is kept in memory for this tab; no request is made.
 */
export function ApprovalGate({
  gateKey,
  revealed,
  pkg,
  inconclusive,
}: {
  gateKey: string;
  revealed: boolean;
  pkg: DeliveryPackage | null;
  inconclusive: boolean;
}) {
  const decision = useSyncExternalStore(subscribe, () => getDecision(gateKey));
  if (!revealed) return null;

  if (!pkg) {
    return (
      <Panel id="decision" title="Recommendation">
        <p className="text-muted">This recording has no delivery package, so there is nothing to approve.</p>
      </Panel>
    );
  }
  if (inconclusive) {
    return (
      <Panel id="decision" title="Recommendation">
        <p>
          Nothing to approve: the diagnosis is inconclusive, so no recommendation rests on verified
          evidence.
        </p>
      </Panel>
    );
  }

  const plan = pkg.diagnosis?.remediation_plan;
  const pending = decision === null;
  return (
    <section
      id="decision"
      aria-labelledby="decision-title"
      className={`relative min-w-0 scroll-mt-144 pt-21 ${pending ? "border-t-2 border-accent" : "border-t border-rule"}`}
    >
      {pending && (
        <p className="label text-accent">
          <span aria-hidden="true" className="mr-8">!</span>
          Decision needed
        </p>
      )}
      <h2 id="decision-title" className="mt-8 text-title">
        Approve the recommendation?
      </h2>
      {pkg.diagnosis?.root_cause && <p className="mt-8 wrap-anywhere">{pkg.diagnosis.root_cause}</p>}
      {!pkg.diagnosis?.root_cause && pkg.summary && <p className="mt-8 wrap-anywhere">{pkg.summary}</p>}

      {plan === null && pkg.diagnosis && (
        <p className="mt-13">
          <Label>Remediation plan</Label> <span className="text-muted">Not recorded</span>
        </p>
      )}
      {plan && plan.length > 0 && (
        <ol className="mt-13 flex flex-col gap-8">
          {plan.map((step, i) => (
            <li key={i} className="min-w-0 border-t border-rule pt-13">
              <div className="flex flex-wrap items-center gap-8">
                <span className="figure text-muted">{String(i + 1).padStart(2, "0")}</span>
                <span className="font-semibold wrap-anywhere">{step.action}</span>
                <Chip tone={step.reversible ? "neutral" : "danger"}>
                  {step.reversible ? "Reversible" : "Not reversible"}
                </Chip>
              </div>
              <p className="mt-8 wrap-anywhere"><span className="text-muted">Why: </span>{step.why}</p>
              <p className="mt-8 wrap-anywhere"><span className="text-muted">Risk: </span>{step.risk}</p>
            </li>
          ))}
        </ol>
      )}

      <p className="mt-21 border-l-2 border-accent pl-13 font-semibold">{NOTHING_RUNS}</p>

      {pending ? (
        <div className="mt-21">
          <ApproveControls
            onApprove={() => recordDecision(gateKey, "approved")}
            onReject={() => recordDecision(gateKey, "rejected")}
          />
        </div>
      ) : (
        <div role="status" className="mt-21 rounded-md border border-rule-strong bg-bg p-21">
          <p className="font-semibold">
            {decision.choice === "approved" ? "You approved the recommendation." : "You rejected the recommendation."}
          </p>
          <p className="mt-8 text-muted">
            Recorded at {formatDate(decision.at)} in this tab&apos;s memory. Reloading the page forgets it.
            Nothing was executed.
          </p>
          <Button className="mt-13" onClick={() => clearDecision(gateKey)}>
            Change my decision
          </Button>
        </div>
      )}
    </section>
  );
}

export function PackagePanel({ pkg, partial }: { pkg: DeliveryPackage; partial: boolean }) {
  return (
    <Panel id="package" title="Delivery package" aside={partial ? <Chip tone="danger">Partial</Chip> : undefined}>
      <Label>Summary</Label>
      <p className="mt-8 wrap-anywhere">{pkg.summary || "No summary recorded."}</p>
      {pkg.deliverables.length > 0 && (
        <div className="mt-13">
          <Label>Deliverables</Label>
          <ul className="mt-8 flex flex-col gap-8">
            {pkg.deliverables.map((d) => (
              <li key={`${d.task_id}-${d.title}`} className="min-w-0 rounded-md border border-rule bg-bg p-13">
                <div className="flex flex-wrap items-center gap-8">
                  <span className="font-semibold wrap-anywhere">{d.title}</span>
                  {partial && <Chip tone="danger">Partial</Chip>}
                </div>
                <pre className="quote mt-8 rounded-sm bg-subtle p-13">
                  {typeof d.content === "string" ? d.content : JSON.stringify(d.content, null, 2)}
                </pre>
              </li>
            ))}
          </ul>
        </div>
      )}
      {pkg.decisions.length > 0 && (
        <div className="mt-13">
          <Label>Decisions the run recorded</Label>
          <ul className="mt-8 list-disc space-y-8 pl-21">
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
    <div role="region" aria-label="Budget stops" className="rounded-lg border-l-4 border-accent bg-withdrawn-tint p-13 sm:p-21">
      <p className="label text-accent">Stopped on budget</p>
      <p className="mt-8 font-semibold">
        {state.stops.length === 1
          ? "One agent stopped on its budget."
          : `${state.stops.length} agents stopped on their budget.`}
        {partial ? " The result below is partial." : ""}
      </p>
      <ul className="mt-8 flex flex-col gap-8">
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
        <p className="mt-8 text-muted">And {state.stops.length - first.length} more, listed in the budget panel.</p>
      )}
    </div>
  );
}

export function TerminalBanner({ state }: { state: RunState }) {
  const t = state.terminal;
  if (!t) return null;
  if (t.kind === "failed") {
    return (
      <div role="region" aria-label="Run failed" className="rounded-lg border-l-4 border-accent bg-withdrawn-tint p-13 sm:p-21">
        <p className="label text-accent">Run failed: {t.code}</p>
        <p className="mt-8 wrap-anywhere">{t.message}</p>
        <p className="mt-8">Spent {formatMicros(toMicros(t.spent))}.</p>
      </div>
    );
  }
  if (t.status === "cancelled") {
    return (
      <div className="rounded-lg border-l-4 border-accent bg-withdrawn-tint p-13 sm:p-21">
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
        <ol className="flex flex-col gap-8">
          {messages.map((m) => (
            <li
              key={m.message_id}
              className={`min-w-0 max-w-[90%] rounded-md p-13 ${
                m.sender === "user" ? "self-end bg-subtle" : "self-start border border-rule"
              }`}
            >
              <Label>{m.sender}</Label>
              <p className="mt-8 wrap-anywhere whitespace-pre-wrap">{m.text}</p>
            </li>
          ))}
        </ol>
      )}
      <form className="mt-13 flex flex-col gap-8" onSubmit={(e) => e.preventDefault()}>
        <label htmlFor="chat-input" className="label text-muted">
          Message
        </label>
        <textarea
          id="chat-input"
          disabled
          aria-describedby="chat-note"
          rows={2}
          className="w-full resize-none rounded-sm border border-rule bg-subtle p-8 text-muted"
        />
        <p id="chat-note" className="text-muted">
          Recorded run: you can read the chat but not write in it.
        </p>
      </form>
    </Panel>
  );
}
