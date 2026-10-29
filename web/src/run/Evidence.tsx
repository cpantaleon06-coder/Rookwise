import { useState } from "react";
import { Chip, Label, Panel, Stamp, type Tone } from "../components/ui";
import { reasonWords, VERDICT_WORDS } from "../lib/labels";
import type { SafeguardRow } from "../lib/safeguards";
import type {
  AuditVerdict,
  ClaimCheck,
  Coverage,
  DeliveryPackage,
  DiagnosisClaim,
} from "../lib/types";

type Filter = "all" | "verified" | "withdrawn";

/** Inconclusive from the typed status, or from the older audit signal (DESIGN 3.4.3). */
export function isInconclusive(pkg: DeliveryPackage | null | undefined, audit: AuditVerdict | null): boolean {
  const typed = pkg?.diagnosis_status?.status;
  if (typed) return typed === "inconclusive";
  return audit?.verdict === "rejected" && (audit.warning ?? "").startsWith("Inconclusive");
}

function NotRecorded() {
  return <span className="text-muted">Not recorded</span>;
}

/**
 * One claim, set as a paragraph of the report: its id, the verdict mark, the
 * text, and the cited lines as a log excerpt. A cited line the check found
 * gets a quiet supported background that fades in; a withdrawn claim's text is
 * struck through, the line drawn left to right once, and its reason sits in a
 * numbered footnote under the list.
 */
function ClaimRow({
  claim,
  check,
  rootCause,
  note,
}: {
  claim: DiagnosisClaim;
  check: ClaimCheck | undefined;
  rootCause: boolean;
  /** The footnote number of a withdrawn claim. */
  note: number | null;
}) {
  const citations = claim.citations;
  const reasons = check?.citation_reasons;
  const withdrawn = check ? !check.supported : false;
  return (
    <li
      className={`min-w-0 border-l-2 pl-21 ${
        withdrawn ? "border-withdrawn" : check?.supported ? "border-supported" : "border-rule"
      }`}
    >
      <div className="ui flex flex-wrap items-baseline justify-between gap-13">
        <p className="flex flex-wrap items-baseline gap-x-13">
          <span className="label text-fg">{claim.claim_id}</span>
          {rootCause && <span className="label text-muted">Root cause rests on this</span>}
        </p>
        {check ? <Stamp kind={check.supported ? "verified" : "withdrawn"} /> : <Chip>Not checked</Chip>}
      </div>
      <p className="mt-8 wrap-anywhere">
        {withdrawn ? <span className="struck strike-draw">{claim.text}</span> : claim.text}
        {withdrawn && note !== null && (
          <sup className="ui ml-8 text-withdrawn">
            <a href={`#note-${claim.claim_id}`} aria-label={`Note ${note}: why ${claim.claim_id} was withdrawn`}>
              {note}
            </a>
          </sup>
        )}
      </p>
      <div className="mt-13">
        {citations === null || citations === undefined ? (
          <p className="ui">
            <Label>Citations</Label> <NotRecorded />
          </p>
        ) : citations.length === 0 ? (
          <p className="ui text-muted">No citation given.</p>
        ) : (
          <ol aria-label={`Lines cited by ${claim.claim_id}`} className="border-y border-rule">
            {citations.map((c, i) => {
              const reason = reasons ? reasons[i] : undefined;
              const failed = !!reason && reason !== "ok";
              const lit = reason === "ok";
              return (
                <li
                  key={`${c.source_id}-${c.line_start}-${i}`}
                  className={`min-w-0 border-b border-rule px-13 py-8 last:border-b-0 ${
                    lit ? "verified-fade bg-supported-tint" : failed ? "bg-withdrawn-tint" : ""
                  }`}
                >
                  <div className="ui flex flex-wrap items-baseline justify-between gap-8">
                    <span className="num wrap-anywhere text-muted">
                      {c.source_id} L{c.line_start}
                      {c.line_end !== c.line_start ? ` to L${c.line_end}` : ""}
                    </span>
                    {reasons === null || reasons === undefined ? (
                      <span className="text-muted">Citation check not recorded</span>
                    ) : lit ? (
                      <span className="label text-supported">
                        <span aria-hidden="true" className="mr-8">✓</span>Citation verified
                      </span>
                    ) : reason ? (
                      <span className="label text-withdrawn">
                        <span aria-hidden="true" className="mr-8">✕</span>
                        <span className="num">{String(reason)}</span>
                      </span>
                    ) : (
                      <span className="text-muted">No check for this citation</span>
                    )}
                  </div>
                  <p className="quote mt-8">{c.quote}</p>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </li>
  );
}

/** The footnotes of the withdrawn claims: the exact reason code and the line that failed. */
function WithdrawalNotes({
  claims,
  checks,
  notes,
}: {
  claims: DiagnosisClaim[];
  checks: Map<string, ClaimCheck>;
  notes: Map<string, number>;
}) {
  const withdrawn = claims.filter((c) => notes.has(c.claim_id));
  if (withdrawn.length === 0) return null;
  return (
    <section aria-label="Notes on withdrawn claims" className="ui mt-21 border-t border-rule pt-13">
      <Label>Notes</Label>
      <ol className="mt-8 flex flex-col gap-13">
        {withdrawn.map((claim) => {
          const check = checks.get(claim.claim_id)!;
          const reasons = check.citation_reasons ?? [];
          const failing = (claim.citations ?? []).filter((_, i) => reasons[i] && reasons[i] !== "ok");
          return (
            <li key={claim.claim_id} id={`note-${claim.claim_id}`} className="grid grid-cols-[21px_1fr] gap-x-8">
              <span className="text-withdrawn">{notes.get(claim.claim_id)}.</span>
              <div className="min-w-0">
                <p>
                  {claim.claim_id} withdrawn. Reason code <span className="num">{String(check.reason)}</span>:{" "}
                  {reasonWords(String(check.reason)).toLowerCase()}.
                </p>
                {failing.length > 0 && (
                  <p className="mt-8 text-muted">
                    Failed {failing.length === 1 ? "line" : "lines"}:{" "}
                    {failing.map((c, i) => (
                      <span key={i} className="num wrap-anywhere">
                        {i > 0 ? ", " : ""}
                        {c.source_id} L{c.line_start}
                        {c.line_end !== c.line_start ? ` to L${c.line_end}` : ""}
                      </span>
                    ))}
                    , shown above in the claim&apos;s cited lines.
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export function EvidencePanel({
  pkg,
  revealed,
  audit,
  corpusCategory,
  statusLabel,
}: {
  pkg: DeliveryPackage | null;
  revealed: boolean;
  audit: AuditVerdict | null;
  corpusCategory: string | null;
  statusLabel: string;
}) {
  const [filter, setFilter] = useState<Filter>("all");

  if (!revealed) {
    return (
      <Panel id="evidence" title="Diagnosis and evidence">
        <p className="text-muted">
          The diagnosis appears after the evidence check, when the replay reaches the end of the run.
          Run status: {statusLabel}.
        </p>
      </Panel>
    );
  }

  const diagnosis = pkg?.diagnosis;
  const check = pkg?.evidence_check;
  if (!diagnosis) {
    return (
      <Panel id="evidence" title="Diagnosis and evidence">
        <p className="text-muted">
          This recording carries no diagnosis or evidence check. Its summary and audit are shown
          below.
        </p>
        {pkg?.summary && <p className="mt-13 wrap-anywhere">{pkg.summary}</p>}
      </Panel>
    );
  }

  const inconclusive = isInconclusive(pkg, audit);
  const checks = new Map((check?.claims ?? []).map((c) => [c.claim_id, c]));
  const rootIds = diagnosis.root_cause_claim_ids;
  const rootSet = new Set(rootIds ?? []);
  const claims = diagnosis.claims ?? [];

  // Root-cause claims first (or withdrawn first when inconclusive); the original order otherwise.
  const ordered = [...claims].sort((a, b) => {
    const rank = (c: DiagnosisClaim) => {
      if (inconclusive) return checks.get(c.claim_id)?.supported === false ? 0 : 1;
      return rootSet.has(c.claim_id) ? 0 : 1;
    };
    return rank(a) - rank(b);
  });
  const visible = ordered.filter((c) => {
    if (filter === "all") return true;
    const r = checks.get(c.claim_id);
    return filter === "verified" ? r?.supported === true : r?.supported === false;
  });

  // Footnote numbers for the withdrawn claims, in the order they are shown.
  const notes = new Map<string, number>();
  for (const c of ordered) if (checks.get(c.claim_id)?.supported === false) notes.set(c.claim_id, notes.size + 1);

  const status = pkg?.diagnosis_status;
  return (
    <Panel id="evidence" title="Diagnosis and evidence">
      <div className="flex flex-col gap-13">
        {inconclusive ? (
          <div>
            <h3 className="text-title text-withdrawn">
              Inconclusive: no root cause is backed by the evidence.
            </h3>
            <p className="mt-8">
              {status?.reason ||
                "Every claim the root cause rested on was withdrawn. The auditor made no model call."}
            </p>
          </div>
        ) : (
          <div>
            <Label>Root cause</Label>
            {diagnosis.root_cause ? (
              <p className="mt-8 wrap-anywhere text-title">
                {diagnosis.root_cause}
              </p>
            ) : (
              <p className="mt-8"><NotRecorded /></p>
            )}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-8">
          <Label>Category</Label>
          <span className="num">{diagnosis.category}</span>
          {status && (
            <Chip tone={status.status === "audited" ? "audit" : "warn"}>
              {status.status === "audited" ? "Audited" : "Inconclusive"}
            </Chip>
          )}
        </div>
        {corpusCategory && (
          <p className="text-muted">
            The incident&apos;s category in the synthetic corpus is{" "}
            <span className="figure text-fg">{corpusCategory}</span>
            {corpusCategory === diagnosis.category
              ? ", the same as the diagnosis."
              : ", not the category the run diagnosed."}
          </p>
        )}
        {check ? (
          <p className="">
            {claims.length} claims: {check.supported} verified, {check.withdrawn} withdrawn
            {check.withdrawn_by_reason && Object.keys(check.withdrawn_by_reason).length > 0 && (
              <span className="text-muted">
                {" "}
                (
                {Object.entries(check.withdrawn_by_reason)
                  .map(([code, n]) => `${n} ${reasonWords(code).toLowerCase()}`)
                  .join(", ")}
                )
              </span>
            )}
            .
          </p>
        ) : (
          <p className="text-muted">The evidence check was not recorded for this run.</p>
        )}
        {rootIds === null || rootIds === undefined ? (
          <p className="">
            <Label>Claims the root cause rests on</Label> <NotRecorded />
          </p>
        ) : null}
        <p className="text-muted">
          A verified claim means its quotes were found in the cited lines. It does not prove the claim is true.
        </p>
      </div>

      <div role="radiogroup" aria-label="Show claims" className="ui mt-21 flex flex-wrap items-center gap-8">
        <Label className="mr-8">Show</Label>
        {(["all", "verified", "withdrawn"] as const).map((f) => (
          <button
            key={f}
            type="button"
            role="radio"
            aria-checked={filter === f}
            onClick={() => setFilter(f)}
            className={`inline-flex min-h-11 items-center rounded-full px-21 font-bold ${
              filter === f ? "bg-fg text-bg" : "border border-rule-strong text-fg hover:border-fg"
            }`}
          >
            {f}
          </button>
        ))}
      </div>
      <ul className="mt-21 flex flex-col gap-34">
        {visible.map((claim) => (
          <ClaimRow
            key={claim.claim_id}
            claim={claim}
            check={checks.get(claim.claim_id)}
            rootCause={rootSet.has(claim.claim_id)}
            note={notes.get(claim.claim_id) ?? null}
          />
        ))}
        {visible.length === 0 && <li className="ui text-muted">No claim matches this filter.</li>}
      </ul>
      <WithdrawalNotes claims={visible} checks={checks} notes={notes} />
    </Panel>
  );
}

const VERDICT_TONE: Record<string, Tone> = {
  accepted: "audit",
  accepted_with_warning: "audit",
  rejected: "warn",
};

export function AuditPanel({ audit }: { audit: AuditVerdict | null }) {
  return (
    <Panel id="audit" title="Audit">
      {!audit ? (
        <p className="text-muted">The auditor has not judged the run yet.</p>
      ) : (
        <div className="flex flex-col gap-13">
          <div className="flex flex-wrap items-center gap-8">
            <Chip tone={VERDICT_TONE[audit.verdict] ?? "neutral"}>
              {VERDICT_WORDS[audit.verdict] ?? audit.verdict}
            </Chip>
            <span className="figure text-muted">{audit.model}</span>
          </div>
          {audit.warning && <p className="wrap-anywhere">{audit.warning}</p>}
          <ul className="flex flex-col gap-8">
            {audit.checks.map((c, i) => (
              <li key={i} className="min-w-0 rounded-md border border-rule bg-bg p-13">
                <div className="flex flex-wrap items-start gap-8">
                  <Chip tone={c.passed ? "ok" : "warn"}>{c.passed ? "Passed" : "Failed"}</Chip>
                  <p className="min-w-0 flex-1 wrap-anywhere font-medium">{c.criterion}</p>
                </div>
                {c.note && <p className="mt-8 wrap-anywhere text-muted">{c.note}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}

const MAX_RANGES = 20;

export function CoveragePanel({ coverage }: { coverage: Coverage }) {
  const unread = coverage.unread_slices ?? [];
  return (
    <Panel id="coverage" title="Coverage">
      <dl className="grid grid-cols-2 divide-x divide-rule sm:grid-cols-3">
        <div className="pr-13">
          <dt><Label>Slices read</Label></dt>
          <dd className="figure">{coverage.slices_read}</dd>
        </div>
        <div className="px-13">
          <dt><Label>Empty slices</Label></dt>
          <dd className="figure">{coverage.empty_slices}</dd>
        </div>
        <div className="col-span-2 mt-13 border-t border-rule pt-13 sm:col-span-1 sm:mt-0 sm:border-t-0 sm:pl-13 sm:pt-0">
          <dt><Label>Unread line ranges</Label></dt>
          <dd className="figure">{unread.length}</dd>
        </div>
      </dl>
      <div className="mt-13">
        {unread.length === 0 ? (
          <p className="text-muted">Every line of every non-empty source was read by a completed task.</p>
        ) : (
          <>
            <p>
              {unread.length} line {unread.length === 1 ? "range was" : "ranges were"} not read by any
              completed task. Findings from those lines are missing.
            </p>
            <ul className="mt-8 flex flex-col gap-8">
              {unread.slice(0, MAX_RANGES).map((r, i) => (
                <li key={i} className="num wrap-anywhere text-muted">
                  {r.source_id} L{r.line_start} to L{r.line_end}
                </li>
              ))}
            </ul>
            {unread.length > MAX_RANGES && (
              <p className="mt-8 text-muted">And {unread.length - MAX_RANGES} more.</p>
            )}
          </>
        )}
        <p className="mt-13">
          <Label>Empty sources</Label>{" "}
          {coverage.empty_sources === null || coverage.empty_sources === undefined ? (
            <NotRecorded />
          ) : coverage.empty_sources.length === 0 ? (
            <span className="text-muted">None</span>
          ) : (
            <span className="figure wrap-anywhere">{coverage.empty_sources.join(", ")}</span>
          )}
        </p>
      </div>
    </Panel>
  );
}

/** Each Shingo label in the mark of what it guards. */
const KIND_MARK: Record<SafeguardRow["kind"], string> = {
  Contact: "text-supported",
  Control: "text-cost",
  Sequence: "text-fg",
  Warning: "text-withdrawn",
  "Second check": "text-auditor",
};

/** Shingo's labels, for the safeguards that fired, set as margin notes. "Caught" means it stopped something. */
export function SafeguardsPanel({ rows, revealed }: { rows: SafeguardRow[]; revealed: boolean }) {
  return (
    <Panel id="safeguards" title="Safeguards that fired in this run">
      {!revealed ? (
        <p className="text-muted">The safeguards appear when the replay reaches the end of the run.</p>
      ) : rows.length === 0 ? (
        <p className="text-muted">This recording carries none of the fields the safeguards report.</p>
      ) : (
        <ol className="flex flex-col gap-13">
          {rows.map((row) => (
            <li key={row.key} className="min-w-0 border-b border-rule pb-13 last:border-b-0">
              <p className="flex flex-wrap items-baseline justify-between gap-8">
                <span className={`label ${KIND_MARK[row.kind]}`}>
                  {row.kind}
                  {row.caught && <span className="ml-8 text-muted">caught</span>}
                </span>
                {row.value !== null && (
                  <span className={row.key === "budget" ? "num text-cost" : "figure font-semibold"}>{row.value}</span>
                )}
              </p>
              <p className="mt-8">{row.title}</p>
              {row.details.length > 0 && (
                <ul className="mt-8 flex flex-col gap-8">
                  {row.details.map((d) => (
                    <li key={d} className="num wrap-anywhere text-muted">
                      {d}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}
