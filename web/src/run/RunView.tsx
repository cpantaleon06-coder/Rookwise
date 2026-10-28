import { useMemo, useSyncExternalStore } from "react";
import { SiteFooter, SiteHeader, SkipLink } from "../components/chrome";
import { getDecision, subscribe } from "../lib/approval";
import { VERDICT_WORDS } from "../lib/labels";
import { atLeastPercent, formatUsd, toMicrosOrNull } from "../lib/money";
import { provenanceOf, summaryOf, type LoadedRecording } from "../lib/recording";
import { runStatusLabel } from "../lib/runState";
import { safeguardRows } from "../lib/safeguards";
import type { LedgerEntry } from "../lib/types";
import { BudgetPanel } from "./Budget";
import { AuditPanel, CoveragePanel, EvidencePanel, isInconclusive, SafeguardsPanel } from "./Evidence";
import { FeedPanel } from "./Feed";
import { ApprovalGate, ChatPanel, PackagePanel, StopBanner, TerminalBanner } from "./Outcome";
import { ProvenanceLine, RecordedBanner, ReplayToolbar, RunHeader } from "./RunHeader";
import { TaskPanel, TeamPanel } from "./Team";
import { useReplay } from "./useReplay";

/**
 * Text for the one polite live region (web/DESIGN.md 5.3). Messages come in
 * the order a run reaches them, so the last one present is the newest; the
 * region announces when it changes.
 */
function announcementOf(messages: (string | null)[]): string {
  return [...messages].reverse().find((m) => m !== null) ?? "";
}

function ledgerSnapshot(ledger: unknown): LedgerEntry[] | null {
  const entries = (ledger as { entries?: unknown } | null | undefined)?.entries;
  return Array.isArray(entries) ? (entries as LedgerEntry[]) : null;
}

export function RunView({ recording }: { recording: LoadedRecording }) {
  const { bundle, events, folder } = recording;
  const replay = useReplay(events);
  const { state, done } = replay;

  const summary = useMemo(() => summaryOf(bundle), [bundle]);
  const provenance = useMemo(() => provenanceOf(bundle), [bundle]);
  const pkg = bundle.package ?? null;
  const revealed = state.terminal !== null || (done && events.length > 0);
  const audit = state.audit ?? (revealed ? (pkg?.audit ?? null) : null);
  const inconclusive = revealed && isInconclusive(pkg, audit);
  const gateKey = `${folder}:${bundle.run.run_id}`;
  const decision = useSyncExternalStore(subscribe, () => getDecision(gateKey));
  const decisionNeeded = revealed && pkg !== null && !inconclusive && decision === null;
  const status = runStatusLabel(state);
  const fallbackCap = bundle.run.caps?.run_usd ?? null;

  const cap = toMicrosOrNull(state.budget?.cap ?? state.cap ?? fallbackCap);
  const spent = toMicrosOrNull(state.budget?.spent);
  const held = toMicrosOrNull(state.budget?.held);
  const nearCap = spent !== null && cap !== null && cap > 0n && atLeastPercent(spent, cap, 80);

  const announcement = announcementOf([
    nearCap ? `Budget at 80 percent of the cap or more: ${formatUsd(state.budget?.spent)} spent.` : null,
    state.stops.length > 0 ? "An agent stopped on its budget." : null,
    state.audit ? `Audit result: ${VERDICT_WORDS[state.audit.verdict] ?? state.audit.verdict}.` : null,
    state.terminal ? `Run ${status.toLowerCase()}.` : null,
    decisionNeeded ? "Decision needed: approve or reject the recommendation." : null,
  ]);

  if (events.length === 0) {
    return (
      <>
        <SiteHeader />
        <RecordedBanner provenance={provenance} summary={summary} notice={null} />
        <main id="run" className="mx-auto flex max-w-[1100px] flex-col items-center px-21 py-55 text-center">
          <h1 className="text-heading text-balance">{summary.title}</h1>
          <p className="mt-13 text-muted">This recording has no events, so there is nothing to replay.</p>
          <a href="#/" className="ui mt-21 inline-block underline">Back to the recordings</a>
        </main>
      </>
    );
  }

  const goal = state.goal ?? bundle.run.goal;
  const corpusCategory = summary.category ?? null;
  const partial = state.terminal?.kind === "finished" ? state.terminal.partial : state.terminal?.partial ?? false;
  const agents = state.agentOrder.map((id) => state.agents.get(id)!).filter(Boolean);
  const safeguards = revealed ? safeguardRows(pkg, audit, { spent, cap, stops: state.stops.length }) : [];

  return (
    <>
      <SkipLink target="run">Skip to the run</SkipLink>
      <SiteHeader />
      <RecordedBanner provenance={provenance} summary={summary} notice={state.modeNotice} />
      <div id="run" className="mx-auto max-w-[1100px] px-21 pt-34 text-center">
        <p className="label text-muted">Recorded investigation</p>
        <h1 className="mt-8 wrap-anywhere text-title text-balance sm:text-heading">{summary.title}</h1>
        <p className="measure mx-auto mt-13 wrap-anywhere text-muted">{goal}</p>
        <ProvenanceLine bundle={bundle} summary={summary} folder={folder} />
      </div>
      <div className="px-21">
        <RunHeader
          status={status}
          budget={{ spent, held, cap, stopped: state.stops.length > 0 }}
          decisionNeeded={decisionNeeded}
          agents={agents}
          escalations={state.escalations.length}
        />
      </div>
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>
      <ReplayToolbar replay={replay} />
      <div className="mx-auto grid max-w-[1100px] gap-x-55 gap-y-34 px-21 py-34 lg:grid-cols-[minmax(0,1.618fr)_minmax(0,1fr)]">
        <main className="flex min-w-0 flex-col gap-34">
          <TerminalBanner state={state} />
          <StopBanner state={state} />
          <EvidencePanel
            pkg={pkg}
            revealed={revealed}
            audit={audit}
            corpusCategory={corpusCategory}
            statusLabel={status}
          />
          <ApprovalGate gateKey={gateKey} revealed={revealed} pkg={pkg} inconclusive={inconclusive} />
          {revealed && pkg && <PackagePanel pkg={pkg} partial={partial} />}
          <FeedPanel state={state} done={done} />
          <TaskPanel state={state} />
        </main>
        <aside aria-label="Margin notes: safeguards, audit, budget and team" className="ui flex min-w-0 flex-col gap-34">
          <SafeguardsPanel rows={safeguards} revealed={revealed} />
          <AuditPanel audit={audit} />
          {revealed && pkg?.coverage && <CoveragePanel coverage={pkg.coverage} />}
          <BudgetPanel
            state={state}
            report={revealed ? (pkg?.cost_report ?? null) : null}
            fallbackCap={fallbackCap}
            snapshot={revealed ? ledgerSnapshot(bundle.ledger) : null}
          />
          <TeamPanel state={state} snapshot={revealed && Array.isArray(bundle.org?.nodes) ? bundle.org!.nodes! : null} />
          <ChatPanel messages={state.messages} />
        </aside>
      </div>
      <SiteFooter />
    </>
  );
}
