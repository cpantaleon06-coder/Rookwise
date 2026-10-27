// Rows for the run view's "Safeguards that fired in this run" panel. Each row
// comes from a field the recording carries; a row whose field is missing is
// left out, so the panel never shows a number the run did not record.

import { reasonWords, VERDICT_WORDS } from "./labels";
import { formatMicros, type Micros } from "./money";
import type { AuditVerdict, DeliveryPackage } from "./types";

export interface SafeguardRow {
  key: string;
  /** Shingo's label for the kind of safeguard. */
  kind: "Contact" | "Control" | "Sequence" | "Warning" | "Second check";
  title: string;
  value: string | null;
  details: string[];
  /** True when the safeguard caught something (a withdrawal, an unread range, a stop). */
  caught: boolean;
}

export function safeguardRows(
  pkg: DeliveryPackage | null | undefined,
  audit: AuditVerdict | null,
  budget: { spent: Micros | null; cap: Micros | null; stops: number },
): SafeguardRow[] {
  const rows: SafeguardRow[] = [];
  const check = pkg?.evidence_check;
  if (check && Array.isArray(check.claims)) {
    rows.push({
      key: "withdrawn",
      kind: "Contact",
      title: "Claims withdrawn by the evidence check",
      value: `${check.withdrawn} of ${check.claims.length}`,
      details: [],
      caught: check.withdrawn > 0,
    });
    const withdrawn = check.claims.filter((c) => !c.supported);
    if (withdrawn.length > 0) {
      rows.push({
        key: "reasons",
        kind: "Contact",
        title: "Withdrawal reasons",
        value: null,
        details: withdrawn.map((c) => `${c.claim_id}: ${reasonWords(String(c.reason))} (${c.reason})`),
        caught: true,
      });
    }
  }
  const coverage = pkg?.coverage;
  if (coverage && typeof coverage.slices_read === "number") {
    rows.push({
      key: "coverage",
      kind: "Warning",
      title: "Slices read",
      value: String(coverage.slices_read),
      details: typeof coverage.empty_slices === "number" ? [`${coverage.empty_slices} empty slices`] : [],
      caught: false,
    });
  }
  if (coverage && Array.isArray(coverage.unread_slices)) {
    const unread = coverage.unread_slices;
    rows.push({
      key: "unread",
      kind: "Warning",
      title: "Unread line ranges declared",
      value: String(unread.length),
      details: unread.slice(0, 5).map((r) => `${r.source_id} L${r.line_start} to L${r.line_end}`),
      caught: unread.length > 0,
    });
  }
  const status = pkg?.diagnosis_status?.status;
  if (status === "inconclusive") {
    rows.push({
      key: "audit",
      kind: "Sequence",
      title: "Audit skipped: nothing survived verification",
      value: "Inconclusive",
      details: pkg?.diagnosis_status?.reason ? [pkg.diagnosis_status.reason] : [],
      caught: true,
    });
  } else if (audit) {
    rows.push({
      key: "audit",
      kind: "Second check",
      title: "Audit by a second model",
      value: VERDICT_WORDS[audit.verdict] ?? audit.verdict,
      details: [status ? `Diagnosis status: ${status}` : null, audit.model].filter((d): d is string => !!d),
      caught: audit.verdict !== "accepted",
    });
  }
  if (budget.spent !== null && budget.cap !== null) {
    rows.push({
      key: "budget",
      kind: "Control",
      title: "Spent against the cap",
      value: `${formatMicros(budget.spent)} of ${formatMicros(budget.cap)}`,
      details: budget.stops > 0 ? [`${budget.stops} ${budget.stops === 1 ? "call" : "calls"} refused on budget`] : [],
      caught: budget.stops > 0,
    });
  }
  return rows;
}
