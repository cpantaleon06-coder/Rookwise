import { useMemo } from "react";
import { SiteFooter, SkipLink } from "../components/chrome";
import { VERDICT_WORDS } from "../lib/labels";
import { atLeastPercent, formatUsd, toMicrosOrNull } from "../lib/money";
import { provenanceOf, summaryOf, type LoadedRecording } from "../lib/recording";
import { runStatusLabel } from "../lib/runState";
import type { LedgerEntry } from "../lib/types";
import { BudgetPanel } from "./Budget";
import { AuditPanel, CoveragePanel, EvidencePanel } from "./Evidence";
import { FeedPanel } from "./Feed";
import { ChatPanel, PackagePanel, StopBanner, TerminalBanner } from "./Outcome";
import { RecordedBanner, ReplayToolbar, RunHeader } from "./RunHeader";
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
  const { bundle, events } = recording;
  const replay = useReplay(events);
  const { state, done } = replay;

  const summary = useMemo(() => summaryOf(bundle), [bundle]);
  const provenance = useMemo(() => provenanceOf(bundle), [bundle]);
  const pkg = bundle.package ?? null;
  const revealed = state.terminal !== null || (done && events.length > 0);
  const audit = state.audit ?? (revealed ? (pkg?.audit ?? null) : null);
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
  ]);

  if (events.length === 0) {
    return (
      <>
        <RecordedBanner provenance={provenance} summary={summary} notice={null} />
        <main id="run" className="mx-auto max-w-[1440px] px-4 py-8 sm:px-6 lg:px-8">
          <h1 className="text-2xl/8 font-semibold">{summary.title}</h1>
          <p className="mt-3 text-muted">This recording has no events, so there is nothing to replay.</p>
          <a href="#/" className="mt-4 inline-block underline underline-offset-4">Back to the recordings</a>
        </main>
      </>
    );
  }

  const goal = state.goal ?? bundle.run.goal;
  const corpusCategory = summary.category ?? null;
  const partial = state.terminal?.kind === "finished" ? state.terminal.partial : state.terminal?.partial ?? false;

  return (
    <>
      <SkipLink target="run">Skip to the run</SkipLink>
      <RecordedBanner provenance={provenance} summary={summary} notice={state.modeNotice} />
      <RunHeader
        status={status}
        goal={goal}
        simulatedCase={state.simulatedCase ?? bundle.run.simulated_case}
        budget={{ spent, held, cap, stopped: state.stops.length > 0 }}
        decisionNeeded={false}
      />
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>
      <ReplayToolbar replay={replay} />
      <div id="run" className="mx-auto max-w-[1440px] px-4 pt-4 sm:px-6 lg:px-8">
        <h1 className="wrap-anywhere text-2xl/8 font-semibold sm:text-[2rem]/[2.5rem]">{summary.title}</h1>
        <p className="mt-1 wrap-anywhere text-sm text-muted sm:hidden">{goal}</p>
      </div>
      <div className="mx-auto grid max-w-[1440px] gap-4 px-4 py-4 sm:px-6 lg:grid-cols-12 lg:gap-6 lg:px-8">
        <main className="flex min-w-0 flex-col gap-4 lg:col-span-8">
          <TerminalBanner state={state} />
          <StopBanner state={state} />
          <EvidencePanel
            pkg={pkg}
            revealed={revealed}
            audit={audit}
            corpusCategory={corpusCategory}
            statusLabel={status}
          />
          <AuditPanel audit={audit} />
          {revealed && pkg?.coverage && <CoveragePanel coverage={pkg.coverage} />}
          {revealed && pkg && <PackagePanel pkg={pkg} partial={partial} />}
          <TeamPanel state={state} snapshot={revealed && Array.isArray(bundle.org?.nodes) ? bundle.org!.nodes! : null} />
          <TaskPanel state={state} />
          <FeedPanel state={state} done={done} />
        </main>
        <aside aria-label="Budget and chat" className="flex min-w-0 flex-col gap-4 lg:col-span-4">
          <BudgetPanel
            state={state}
            report={revealed ? (pkg?.cost_report ?? null) : null}
            fallbackCap={fallbackCap}
            snapshot={revealed ? ledgerSnapshot(bundle.ledger) : null}
          />
          <ChatPanel messages={state.messages} />
        </aside>
      </div>
      <SiteFooter />
    </>
  );
}
