// TypeScript view of the parts of API contract v1 the replay uses
// (core/api/models.py, docs/api/schemas/). Money fields are six-decimal strings.
// Fields marked "added 2026-10-25" are optional: older recordings do not carry
// them, and a null there means "not recorded", never an empty list.

export type Level = "vp" | "director" | "manager" | "operator" | "auditor";
export type AgentStatus = "hired" | "working" | "idle" | "done" | "failed";

export interface AgentNode {
  agent_id: string;
  level: Level;
  role: string;
  model: string;
  operator_id: string | null;
  parent_id: string | null;
  skills: string[];
  tools: string[];
  status: AgentStatus;
}

export interface TaskBudget {
  max_input_tokens: number;
  max_output_tokens: number;
  max_usd: string;
}

export interface TaskV1 {
  task_id: string;
  run_id: string;
  role: string;
  instruction_ref: string;
  inputs: unknown[];
  budget: TaskBudget;
  deadline_s: number;
}

export interface ResultV1 {
  task_id: string;
  status: "ok" | "failed";
  output_ref: string | null;
  usage: { input_tokens: number; output_tokens: number; usd: string };
  self_check: { schema_valid: boolean; notes: string };
}

export interface AttemptRecord {
  task_id: string;
  attempt_index: number;
  model: string;
  protocol: string;
  reason: "first" | "repair" | "escalation";
  retry_reason: string | null;
  loop_status: string;
  ok: boolean;
  validation_errors: string[];
  length_retries: number;
  steps: number;
  model_calls: number;
  tool_calls: Record<string, number>;
  usd: string;
  input_tokens: number;
  output_tokens: number;
  usage_estimated: boolean;
  detail: string;
}

export interface LedgerEntry {
  run_id: string;
  level: Level;
  task_id: string;
  model: string;
  input_tokens: number;
  cached_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  cached_price_fallback: boolean;
  usd_real: string;
  usd_predicted: string;
  ts: string;
  skills: string[];
  usage_estimated: boolean;
}

export interface ChatMessage {
  message_id: string;
  run_id: string;
  sender: string;
  text: string;
  ts: string;
}

export interface AuditCheck {
  criterion: string;
  passed: boolean;
  note: string;
}

export interface AuditVerdict {
  verdict: "accepted" | "accepted_with_warning" | "rejected" | string;
  model: string;
  checks: AuditCheck[];
  correction_cycles: number;
  warning: string | null;
}

export interface ErrorBody {
  code: string;
  message: string;
  details?: Record<string, unknown> | null;
}

// -- Events -------------------------------------------------------------------------------

interface Envelope<T extends string, P> {
  id: string;
  seq: number;
  run_id: string;
  mode: "recorded" | "live";
  ts: string;
  type: T;
  payload: P;
}

export type RunStartedEvent = Envelope<
  "run_started",
  {
    goal: string;
    mode: string;
    recording_id: string | null;
    budget_usd: string;
    board: boolean;
    simulated_case: boolean;
  }
>;
export type AgentHiredEvent = Envelope<"agent_hired", { agent: AgentNode }>;
export type TaskAssignedEvent = Envelope<
  "task_assigned",
  { task: TaskV1; agent_id: string; operator_id: string | null }
>;
export type TaskStartedEvent = Envelope<
  "task_started",
  { task_id: string; agent_id: string; model: string; attempt_index: number }
>;
export type AttemptRecordedEvent = Envelope<
  "attempt_recorded",
  { agent_id: string; attempt: AttemptRecord }
>;
export type ToolCalledEvent = Envelope<
  "tool_called",
  {
    task_id: string;
    agent_id: string;
    tool: string;
    ok: boolean;
    error_type: string | null;
    truncated: boolean;
    run_tool_count: number;
    args: unknown;
  }
>;
export type BudgetUpdateEvent = Envelope<
  "budget_update",
  {
    spent_usd: string;
    held_usd: string;
    predicted_usd: string;
    cap_usd: string;
    spent_by_level: Record<string, string>;
    entry: LedgerEntry | null;
  }
>;
export type BudgetAllocationEvent = Envelope<
  "budget_allocation",
  {
    action: "allocated" | "released";
    agent_id: string;
    parent_agent_id: string | null;
    usd: string;
    parent_free_usd: string;
  }
>;
export type BudgetExhaustedEvent = Envelope<
  "budget_exhausted",
  {
    agent_id: string;
    level: Level;
    scope: string;
    key: string;
    cap_usd: string;
    committed_usd: string;
    requested_usd: string;
  }
>;
export type MessageEvent = Envelope<"message", { message: ChatMessage }>;
export type TaskResultEvent = Envelope<
  "task_result",
  { agent_id: string; result: ResultV1; label: string }
>;
export type EscalationEvent = Envelope<
  "escalation",
  { from_agent_id: string; to_agent_id: string; task_id: string | null; reason: string }
>;
export type AuditResultEvent = Envelope<"audit_result", { audit: AuditVerdict }>;
export type RunFinishedEvent = Envelope<
  "run_finished",
  {
    status: string;
    partial: boolean;
    spent_usd: string;
    predicted_usd: string;
    package_url: string | null;
  }
>;
export type RunFailedEvent = Envelope<
  "run_failed",
  { error: ErrorBody; partial: boolean; spent_usd: string }
>;
export type ModeNoticeEvent = Envelope<
  "mode_notice",
  { notice: string; mode: string; refusal: string | null; detail: string }
>;

export type RunEvent =
  | RunStartedEvent
  | AgentHiredEvent
  | TaskAssignedEvent
  | TaskStartedEvent
  | AttemptRecordedEvent
  | ToolCalledEvent
  | BudgetUpdateEvent
  | BudgetAllocationEvent
  | BudgetExhaustedEvent
  | MessageEvent
  | TaskResultEvent
  | EscalationEvent
  | AuditResultEvent
  | RunFinishedEvent
  | RunFailedEvent
  | ModeNoticeEvent;

export type EventType = RunEvent["type"];

export interface TimedEvent {
  delay_ms: number;
  event: RunEvent;
}

export interface EventsFile {
  run_id: string;
  events: TimedEvent[];
  _fixture?: unknown;
  _recording?: unknown;
}

// -- Bundle sections ----------------------------------------------------------------------

export interface RecordingSummary {
  recording_id: string;
  title: string;
  goal: string;
  simulated_case: boolean;
  spent_usd: string;
  // added 2026-10-25
  recorded_at?: string | null;
  incident_id?: string | null;
  category?: string | null;
}

export interface RunView {
  run_id: string;
  goal: string;
  mode: string;
  recording_id: string | null;
  simulated_case: boolean;
  status: string;
  board: boolean;
  caps: { run_usd: string; level_usd: Record<string, string> };
  spent_usd: string;
  held_usd: string;
  predicted_usd: string;
  created_at: string;
  finished_at: string | null;
  events_url: string;
}

export interface CostReport {
  predicted_usd: string;
  real_usd: string;
  prediction_error: number | null;
  spent_by_level: Record<string, string>;
  usage_estimated_entries: number;
}

export interface Deliverable {
  task_id: string;
  output_ref: string | null;
  title: string;
  content: unknown;
}

// added 2026-10-25
export interface DiagnosisCitation {
  source_id: string;
  line_start: number;
  line_end: number;
  quote: string;
}

export interface DiagnosisClaim {
  claim_id: string;
  text: string;
  citations?: DiagnosisCitation[] | null;
}

export interface RemediationStep {
  action: string;
  why: string;
  risk: string;
  reversible: boolean;
}

export interface Diagnosis {
  root_cause?: string | null;
  category: string;
  claims: DiagnosisClaim[];
  root_cause_claim_ids?: string[] | null;
  remediation_plan?: RemediationStep[] | null;
}

export type ClaimReason =
  | "ok"
  | "no_citations"
  | "source_missing"
  | "line_out_of_range"
  | "quote_not_found";

export interface ClaimCheck {
  claim_id: string;
  supported: boolean;
  reason: ClaimReason | string;
  citation_reasons?: (ClaimReason | string)[] | null;
}

export interface EvidenceCheck {
  claims: ClaimCheck[];
  supported: number;
  withdrawn: number;
  withdrawn_by_reason?: Record<string, number>;
}

export interface DiagnosisStatus {
  status: "audited" | "inconclusive" | string;
  reason?: string;
}

export interface LineRange {
  source_id: string;
  line_start: number;
  line_end: number;
}

export interface Coverage {
  slices_read: number;
  empty_slices: number;
  unread_slices?: LineRange[];
  empty_sources?: string[] | null;
}

export interface DeliveryPackage {
  run_id: string;
  mode: string;
  simulated_case: boolean;
  summary: string;
  deliverables: Deliverable[];
  cost_report: CostReport;
  contracts: unknown[];
  decisions: string[];
  audit: AuditVerdict;
  // added 2026-10-25
  diagnosis?: Diagnosis | null;
  evidence_check?: EvidenceCheck | null;
  diagnosis_status?: DiagnosisStatus | null;
  coverage?: Coverage | null;
}

export interface RecordedBundle {
  _fixture?: { synthetic?: boolean; note?: string } & Record<string, unknown>;
  _recording?: { real_model_output?: boolean; synthetic_corpus?: boolean } & Record<
    string,
    unknown
  >;
  modes?: { recordings?: RecordingSummary[] } & Record<string, unknown>;
  recording?: RecordingSummary;
  run: RunView;
  org?: { nodes?: AgentNode[] } & Record<string, unknown>;
  ledger?: unknown;
  messages?: { items?: ChatMessage[] } & Record<string, unknown>;
  tasks?: unknown;
  package?: DeliveryPackage | null;
}
