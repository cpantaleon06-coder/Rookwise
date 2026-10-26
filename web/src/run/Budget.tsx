import { Label, Meter, Panel, Usd } from "../components/ui";
import { agentName } from "../lib/feed";
import { LEVEL_WORDS } from "../lib/labels";
import { formatMicros, percentOf, toMicros, toMicrosOrNull, type Micros } from "../lib/money";
import type { RunState } from "../lib/runState";
import type { CostReport, LedgerEntry } from "../lib/types";

function Pill({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex max-w-full flex-wrap items-center gap-1.5 rounded-full border border-line px-3 py-1 text-sm">
      <span className="label text-muted">{label}</span>
      <span className="num">{value}</span>
    </span>
  );
}

function Bar({ label, value, max }: { label: string; value: Micros; max: Micros }) {
  return (
    <div className="grid grid-cols-[5.5rem_1fr] items-center gap-3">
      <Label>{label}</Label>
      <div className="flex min-w-0 items-center gap-2">
        <div className="h-2 min-w-0 flex-1 rounded-full bg-track">
          <div className="h-2 rounded-full bg-ink" style={{ width: `${percentOf(value, max)}%` }} />
        </div>
        <span className="num shrink-0 text-sm">{formatMicros(value)}</span>
      </div>
    </div>
  );
}

function PredictedVersusReal({
  predicted,
  real,
  report,
}: {
  predicted: Micros;
  real: Micros;
  report: CostReport | null;
}) {
  const max = predicted > real ? predicted : real;
  const diff = real - predicted;
  const ratio = report?.prediction_error;
  return (
    <div className="flex flex-col gap-2">
      <Bar label="Predicted" value={predicted} max={max} />
      <Bar label="Real" value={real} max={max} />
      <p className="text-sm">
        {diff === 0n
          ? "Real equals predicted."
          : diff > 0n
            ? `Real is ${formatMicros(diff)} above predicted`
            : `Real is ${formatMicros(-diff)} below predicted`}
        {diff !== 0n && typeof ratio === "number" && Number.isFinite(ratio)
          ? ` (${Math.abs(ratio * 100).toFixed(1)} percent).`
          : diff !== 0n
            ? "."
            : ""}
      </p>
      <p className="text-sm text-muted">
        Predicted is the sum of the estimates made before each call, not an estimate of the whole run
        made up front.
      </p>
    </div>
  );
}

export function BudgetPanel({
  state,
  report,
  fallbackCap,
  snapshot,
}: {
  state: RunState;
  report: CostReport | null;
  fallbackCap: string | null;
  /** The bundle's final ledger entries, passed once the replay reached the end. */
  snapshot: LedgerEntry[] | null;
}) {
  const ledger = snapshot ?? state.ledger;
  const b = state.budget;
  const cap = toMicrosOrNull(b?.cap ?? state.cap ?? fallbackCap);
  const spent = b ? toMicros(b.spent) : null;
  const held = b ? toMicros(b.held) : null;
  const predicted = b ? toMicros(b.predicted) : null;
  const levels = report?.spent_by_level ?? b?.spentByLevel ?? {};
  const estimated = ledger.filter((e) => e.usage_estimated).length;
  const allocations = state.agentOrder
    .map((id) => state.agents.get(id)!)
    .filter((a) => a.allocated !== null);

  return (
    <Panel id="budget" title="Budget (USD)">
      {spent === null ? (
        <div className="flex flex-col gap-3">
          <p className="num text-[2.5rem]/[2.75rem] font-medium text-muted">Not started</p>
          <Pill label="Cap" value={cap === null ? "Not recorded" : formatMicros(cap)} />
          <Meter spent={null} held={null} cap={cap} stopped={false} />
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <div>
            <Label>Spent</Label>
            <p className="num wrap-anywhere text-[2.5rem]/[2.75rem] font-medium">{formatMicros(spent)}</p>
            <p className="text-xs text-muted">As of event {state.applied.length} of the replay.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Pill label="Reserved" value={held === null ? "Not started" : formatMicros(held)} />
            <Pill label="Cap" value={cap === null ? "Not recorded" : formatMicros(cap)} />
            <Pill label="Predicted" value={predicted === null ? "Not started" : formatMicros(predicted)} />
          </div>
          <Meter spent={spent} held={held} cap={cap} stopped={state.stops.length > 0} />

          <div className="border-t border-line pt-4">
            <h3 className="mb-3 font-semibold">Predicted versus real</h3>
            {report ? (
              <PredictedVersusReal
                predicted={toMicros(report.predicted_usd)}
                real={toMicros(report.real_usd)}
                report={report}
              />
            ) : predicted !== null ? (
              <PredictedVersusReal predicted={predicted} real={spent} report={null} />
            ) : null}
            {report && <p className="mt-1 text-xs text-muted">From the run&apos;s cost report.</p>}
          </div>

          <div className="border-t border-line pt-4">
            <h3 className="mb-2 font-semibold">By level</h3>
            {Object.keys(levels).length === 0 ? (
              <p className="text-sm text-muted">Nothing charged yet.</p>
            ) : (
              <dl className="flex flex-col gap-1 text-sm">
                {Object.entries(levels).map(([level, usd]) => (
                  <div key={level} className="flex justify-between gap-3">
                    <dt>{LEVEL_WORDS[level] ?? level}</dt>
                    <dd><Usd value={usd} /></dd>
                  </div>
                ))}
              </dl>
            )}
            <p className="mt-2 text-xs text-muted">Predicted cost per level is not in the recording.</p>
          </div>

          {state.stops.length > 0 && (
            <div className="border-t border-line pt-4">
              <h3 className="mb-2 font-semibold text-danger">Stops ({state.stops.length})</h3>
              <ul className="flex flex-col gap-2 text-sm">
                {state.stops.map((s, i) => (
                  <li key={i} className="rounded-[10px] bg-danger-tint p-3">
                    <span className="font-medium">{agentName(state.agents, s.agent_id)}</span> stopped on its{" "}
                    {s.scope} cap of <Usd value={s.cap_usd} />: it needed <Usd value={s.requested_usd} />{" "}
                    with <Usd value={s.committed_usd} /> committed.
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="border-t border-line pt-4 text-sm">
            {estimated === 0
              ? "Every charge so far used the usage the model reported."
              : `${estimated} ${estimated === 1 ? "charge was" : "charges were"} estimated (no usage returned).`}
          </p>

          {allocations.length > 0 && (
            <details className="border-t border-line pt-4">
              <summary className="min-h-11 cursor-pointer font-semibold">
                Sub-budgets ({allocations.length})
              </summary>
              <ul className="mt-2 flex flex-col gap-2 text-sm">
                {allocations.map((a) => (
                  <li key={a.node.agent_id} className="rounded-[10px] border border-line p-3">
                    <p className="font-medium wrap-anywhere">{agentName(state.agents, a.node.agent_id)}</p>
                    <p className="text-muted">
                      Held <span className="num text-ink">{formatMicros(a.allocated ?? 0n)}</span>
                      {a.released !== null && (
                        <>
                          , released <span className="num text-ink">{formatMicros(a.released)}</span>
                        </>
                      )}
                      {a.node.level === "operator" && (
                        <>
                          , spent <span className="num text-ink">{formatMicros(a.spent)}</span>
                        </>
                      )}
                    </p>
                  </li>
                ))}
              </ul>
            </details>
          )}

          <details className="border-t border-line pt-4">
            <summary className="min-h-11 cursor-pointer font-semibold">
              Ledger ({ledger.length} {ledger.length === 1 ? "entry" : "entries"})
            </summary>
            <p className="mt-2 text-xs text-muted">
              {snapshot
                ? "From the ledger the recording kept at the end of the run."
                : "From the charges the replay has shown so far."}
            </p>
            <ol className="mt-2 flex flex-col gap-2 text-sm">
              {ledger.map((e, i) => (
                <li key={i} className="min-w-0 rounded-[10px] border border-line p-3">
                  <div className="flex flex-wrap justify-between gap-2">
                    <span className="font-medium">
                      {LEVEL_WORDS[e.level] ?? e.level} <span className="num text-muted">{e.task_id}</span>
                    </span>
                    <span className="num">{formatMicros(toMicros(e.usd_real))}</span>
                  </div>
                  <p className="num wrap-anywhere text-xs text-muted">{e.model}</p>
                  <p className="num text-xs text-muted">
                    in {e.input_tokens}, cached {e.cached_tokens}, out {e.output_tokens}; predicted{" "}
                    {formatMicros(toMicros(e.usd_predicted))}
                    {e.usage_estimated ? "; usage estimated" : ""}
                    {e.cached_price_fallback && e.cached_tokens > 0 ? "; cached at input price" : ""}
                  </p>
                </li>
              ))}
            </ol>
          </details>
        </div>
      )}
    </Panel>
  );
}
