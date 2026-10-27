// Facts of one recorded run, read from its bundle for the landing's floating
// pills and ticker. A fact is null when the recording does not carry it, and
// the page then leaves it out: no number here is computed from a guess.

import { isMoney } from "./money";
import type { DeliveryPackage, RecordedBundle } from "./types";

export interface RunFacts {
  spentUsd: string | null;
  capUsd: string | null;
  slicesRead: number | null;
  emptySlices: number | null;
  unreadRanges: number | null;
  claims: number | null;
  supported: number | null;
  withdrawn: number | null;
  /** The first claim the evidence check verified. */
  verifiedClaimId: string | null;
  /** The first withdrawn claim and its reason code. */
  withdrawnClaimId: string | null;
  withdrawnReason: string | null;
  auditVerdict: string | null;
  diagnosisStatus: string | null;
  category: string | null;
  operators: number | null;
}

function money(value: unknown): string | null {
  return typeof value === "string" && isMoney(value) ? value : null;
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function packageFacts(pkg: DeliveryPackage | null | undefined) {
  const check = pkg?.evidence_check ?? null;
  const claims = check && Array.isArray(check.claims) ? check.claims : null;
  const verified = claims?.find((c) => c.supported) ?? null;
  const withdrawn = claims?.find((c) => !c.supported) ?? null;
  const coverage = pkg?.coverage ?? null;
  return {
    slicesRead: count(coverage?.slices_read),
    emptySlices: count(coverage?.empty_slices),
    unreadRanges: Array.isArray(coverage?.unread_slices) ? coverage!.unread_slices!.length : null,
    claims: claims ? claims.length : null,
    supported: count(check?.supported),
    withdrawn: count(check?.withdrawn),
    verifiedClaimId: verified?.claim_id ?? null,
    withdrawnClaimId: withdrawn?.claim_id ?? null,
    withdrawnReason: withdrawn ? String(withdrawn.reason) : null,
    auditVerdict: pkg?.audit?.verdict ?? null,
    diagnosisStatus: pkg?.diagnosis_status?.status ?? null,
    category: pkg?.diagnosis?.category ?? null,
  };
}

export function runFacts(bundle: RecordedBundle): RunFacts {
  const nodes = bundle.org?.nodes;
  return {
    spentUsd: money(bundle.run.spent_usd),
    capUsd: money(bundle.run.caps?.run_usd),
    ...packageFacts(bundle.package),
    operators: Array.isArray(nodes) ? nodes.filter((n) => n.level === "operator").length : null,
  };
}
