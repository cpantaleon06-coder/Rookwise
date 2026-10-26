import { useState } from "react";
import { Chip, Label, Panel, type Tone } from "../components/ui";
import { reasonWords, VERDICT_WORDS } from "../lib/labels";
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

function ClaimRow({
  claim,
  check,
  rootCause,
}: {
  claim: DiagnosisClaim;
  check: ClaimCheck | undefined;
  rootCause: boolean;
}) {
  const citations = claim.citations;
  const reasons = check?.citation_reasons;
  const withdrawn = check ? !check.supported : false;
  return (
    <li
      className={`min-w-0 rounded-[10px] border border-line p-4 ${withdrawn ? "bg-danger-tint" : "bg-surface"}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        {!check && <Chip>Not checked</Chip>}
        {check && check.supported && <Chip tone="ok">Verified</Chip>}
        {check && !check.supported && (
          <Chip tone="danger">Withdrawn: {reasonWords(String(check.reason))}</Chip>
        )}
        <Label>{claim.claim_id}</Label>
        {rootCause && <Label className="text-ink">Root cause rests on this</Label>}
      </div>
      <p className="mt-2 wrap-anywhere text-lg/7 font-semibold">{claim.text}</p>
      {check && !check.supported && (
        <p className="mt-1 text-sm text-danger">
          Reason code <span className="num">{check.reason}</span>.
        </p>
      )}
      <div className="mt-3">
        {citations === null || citations === undefined ? (
          <p className="text-sm">
            <Label>Citations</Label> <NotRecorded />
          </p>
        ) : citations.length === 0 ? (
          <p className="text-sm text-muted">No citation given.</p>
        ) : (
          <ol className="flex flex-col gap-2">
            {citations.map((c, i) => {
              const reason = reasons ? reasons[i] : undefined;
              return (
                <li key={`${c.source_id}-${c.line_start}-${i}`} className="min-w-0 rounded-[6px] bg-raised p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <Label className="wrap-anywhere">
                      {c.source_id} L{c.line_start}
                      {c.line_end !== c.line_start ? ` to L${c.line_end}` : ""}
                    </Label>
                    {reasons === null || reasons === undefined ? (
                      <span className="text-xs text-muted">Citation check not recorded</span>
                    ) : reason === "ok" ? (
                      <Chip tone="ok">Citation verified</Chip>
                    ) : reason ? (
                      <Chip tone="danger">{reasonWords(String(reason))}</Chip>
                    ) : (
                      <span className="text-xs text-muted">No check for this citation</span>
                    )}
                  </div>
                  <p className="quote mt-2">{c.quote}</p>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </li>
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
        {pkg?.summary && <p className="mt-3 wrap-anywhere">{pkg.summary}</p>}
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

  const status = pkg?.diagnosis_status;
  return (
    <Panel id="evidence" title="Diagnosis and evidence">
      <div className="flex flex-col gap-3">
        {inconclusive ? (
          <div>
            <h3 className="text-2xl/8 font-semibold text-danger sm:text-[2rem]/[2.5rem]">
              Inconclusive: no root cause is backed by the evidence.
            </h3>
            <p className="mt-2 text-sm">
              {status?.reason ||
                "Every claim the root cause rested on was withdrawn. The auditor made no model call."}
            </p>
          </div>
        ) : (
          <div>
            <Label>Root cause</Label>
            {diagnosis.root_cause ? (
              <p className="mt-1 wrap-anywhere text-2xl/8 font-semibold sm:text-[2rem]/[2.5rem]">
                {diagnosis.root_cause}
              </p>
            ) : (
              <p className="mt-1"><NotRecorded /></p>
            )}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Label>Category</Label>
          <span className="num rounded-full border border-line-strong px-2.5 py-0.5 text-sm">{diagnosis.category}</span>
          {status && (
            <Chip tone={status.status === "audited" ? "ok" : "danger"}>
              {status.status === "audited" ? "Audited" : "Inconclusive"}
            </Chip>
          )}
        </div>
        {corpusCategory && (
          <p className="text-sm text-muted">
            The incident&apos;s category in the synthetic corpus is{" "}
            <span className="num text-ink">{corpusCategory}</span>
            {corpusCategory === diagnosis.category
              ? ", the same as the diagnosis."
              : ", not the category the run diagnosed."}
          </p>
        )}
        {check ? (
          <p className="text-sm">
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
          <p className="text-sm text-muted">The evidence check was not recorded for this run.</p>
        )}
        {rootIds === null || rootIds === undefined ? (
          <p className="text-sm">
            <Label>Claims the root cause rests on</Label> <NotRecorded />
          </p>
        ) : null}
        <p className="text-sm text-muted">
          A verified claim means its quotes were found in the cited lines. It does not prove the claim is true.
        </p>
      </div>

      <div role="radiogroup" aria-label="Show claims" className="mt-5 flex flex-wrap items-center gap-1">
        <Label className="mr-2">Show</Label>
        {(["all", "verified", "withdrawn"] as const).map((f) => (
          <button
            key={f}
            type="button"
            role="radio"
            aria-checked={filter === f}
            onClick={() => setFilter(f)}
            className={`label inline-flex min-h-11 items-center rounded-full px-3 ${
              filter === f ? "bg-primary text-on-primary" : "border border-line-strong hover:bg-raised"
            }`}
          >
            {f}
          </button>
        ))}
      </div>
      <ul className="mt-4 flex flex-col gap-3">
        {visible.map((claim) => (
          <ClaimRow
            key={claim.claim_id}
            claim={claim}
            check={checks.get(claim.claim_id)}
            rootCause={rootSet.has(claim.claim_id)}
          />
        ))}
        {visible.length === 0 && <li className="text-muted">No claim matches this filter.</li>}
      </ul>
    </Panel>
  );
}

const VERDICT_TONE: Record<string, Tone> = {
  accepted: "ok",
  accepted_with_warning: "neutral",
  rejected: "danger",
};

export function AuditPanel({ audit }: { audit: AuditVerdict | null }) {
  return (
    <Panel id="audit" title="Audit">
      {!audit ? (
        <p className="text-muted">The auditor has not judged the run yet.</p>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone={VERDICT_TONE[audit.verdict] ?? "neutral"}>
              {VERDICT_WORDS[audit.verdict] ?? audit.verdict}
            </Chip>
            <span className="num text-sm text-muted">{audit.model}</span>
          </div>
          {audit.warning && <p className="wrap-anywhere text-sm">{audit.warning}</p>}
          <ul className="flex flex-col gap-2">
            {audit.checks.map((c, i) => (
              <li key={i} className="min-w-0 rounded-[10px] border border-line p-3">
                <div className="flex flex-wrap items-start gap-2">
                  <Chip tone={c.passed ? "ok" : "danger"}>{c.passed ? "Passed" : "Failed"}</Chip>
                  <p className="min-w-0 flex-1 wrap-anywhere text-sm font-medium">{c.criterion}</p>
                </div>
                {c.note && <p className="mt-2 wrap-anywhere text-sm text-muted">{c.note}</p>}
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
      <dl className="grid grid-cols-2 divide-x divide-line sm:grid-cols-3">
        <div className="pr-3">
          <dt><Label>Slices read</Label></dt>
          <dd className="num text-lg">{coverage.slices_read}</dd>
        </div>
        <div className="px-3">
          <dt><Label>Empty slices</Label></dt>
          <dd className="num text-lg">{coverage.empty_slices}</dd>
        </div>
        <div className="col-span-2 mt-3 border-t border-line pt-3 sm:col-span-1 sm:mt-0 sm:border-t-0 sm:pl-3 sm:pt-0">
          <dt><Label>Unread line ranges</Label></dt>
          <dd className="num text-lg">{unread.length}</dd>
        </div>
      </dl>
      <div className="mt-4 text-sm">
        {unread.length === 0 ? (
          <p className="text-muted">Every line of every non-empty source was read by a completed task.</p>
        ) : (
          <>
            <p>
              {unread.length} line {unread.length === 1 ? "range was" : "ranges were"} not read by any
              completed task. Findings from those lines are missing.
            </p>
            <ul className="mt-2 flex flex-col gap-1">
              {unread.slice(0, MAX_RANGES).map((r, i) => (
                <li key={i} className="num wrap-anywhere text-muted">
                  {r.source_id} L{r.line_start} to L{r.line_end}
                </li>
              ))}
            </ul>
            {unread.length > MAX_RANGES && (
              <p className="mt-1 text-muted">And {unread.length - MAX_RANGES} more.</p>
            )}
          </>
        )}
        <p className="mt-3">
          <Label>Empty sources</Label>{" "}
          {coverage.empty_sources === null || coverage.empty_sources === undefined ? (
            <NotRecorded />
          ) : coverage.empty_sources.length === 0 ? (
            <span className="text-muted">None</span>
          ) : (
            <span className="num wrap-anywhere">{coverage.empty_sources.join(", ")}</span>
          )}
        </p>
      </div>
    </Panel>
  );
}
