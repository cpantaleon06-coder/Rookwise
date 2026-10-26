// Words for codes. Copy follows web/DESIGN.md section 1.4 and section 4.

export const CLAIM_REASON_WORDS: Record<string, string> = {
  ok: "Verified",
  no_citations: "No citation given",
  source_missing: "Cited source does not exist",
  line_out_of_range: "Cited lines are outside the source",
  quote_not_found: "Quote is not in the cited lines",
};

export function reasonWords(code: string): string {
  return CLAIM_REASON_WORDS[code] ?? code.replace(/_/g, " ");
}

export const VERDICT_WORDS: Record<string, string> = {
  accepted: "Accepted",
  accepted_with_warning: "Accepted with a warning",
  rejected: "Rejected",
};

export const LEVEL_WORDS: Record<string, string> = {
  vp: "VP",
  director: "Director",
  manager: "Manager",
  operator: "Operator",
  auditor: "Auditor",
};

export const TASK_LABEL_WORDS: Record<string, string> = {
  first_pass_ok: "First pass",
  ok_after_retry: "OK after retry",
  ok_after_escalation: "OK after escalation",
  failed: "Failed",
};

export const ATTEMPT_REASON_WORDS: Record<string, string> = {
  first: "first pass",
  repair: "retry",
  escalation: "escalation",
};

export const AGENT_STATUS_WORDS: Record<string, string> = {
  hired: "Hired",
  working: "Working",
  idle: "Idle",
  done: "Done",
  failed: "Failed",
  stopped: "Stopped: budget",
};

/** "nemotron-3.5-lightning" stays as is; ids are never parsed, only shown. */
export function shortModel(model: string): string {
  return model;
}

export function formatDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

/** Seconds since the start, for the feed: "+12.4 s". */
export function elapsed(startIso: string | null, iso: string): string {
  if (!startIso) return "";
  const start = Date.parse(startIso);
  const at = Date.parse(iso);
  if (Number.isNaN(start) || Number.isNaN(at)) return "";
  return `+${((at - start) / 1000).toFixed(1)} s`;
}
