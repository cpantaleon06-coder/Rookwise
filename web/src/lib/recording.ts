// Loading a recording folder and summarizing it. A recording folder holds two
// files, recorded_run.json (the bundle) and recorded_run.events.json (the
// stream). Any folder with those two names works. This module is shared by the
// app and by the Vite plugin that writes recordings/index.json at build time.

import { isMoney } from "./money.ts";
import { prepareEvents } from "./replay.ts";
import type {
  ClaimReason,
  DiagnosisCitation,
  RecordedBundle,
  RecordingSummary,
  TimedEvent,
} from "./types.ts";

export const BUNDLE_FILE = "recorded_run.json";
export const EVENTS_FILE = "recorded_run.events.json";
export const INDEX_FILE = "index.json";

/** Folder names are plain path segments; anything else is refused before fetching. */
export const FOLDER_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/;

export type Provenance = "synthetic_fixture" | "real_model_output" | "unknown";

export interface ClaimExcerpt {
  text: string;
  citation: DiagnosisCitation | null;
  reason: ClaimReason | string;
}

export interface RunExcerpt {
  verified: ClaimExcerpt | null;
  withdrawn: ClaimExcerpt | null;
}

export interface IndexEntry {
  folder: string;
  summary: RecordingSummary;
  provenance: Provenance;
  status: string;
  capUsd: string | null;
  excerpt: RunExcerpt | null;
}

export interface RecordingIndex {
  recordings: IndexEntry[];
}

export interface LoadedRecording {
  folder: string;
  bundle: RecordedBundle;
  events: TimedEvent[];
}

export type LoadErrorKind = "invalid_name" | "not_found" | "network" | "invalid";

export class RecordingError extends Error {
  readonly kind: LoadErrorKind;
  constructor(kind: LoadErrorKind, message: string) {
    super(message);
    this.kind = kind;
    this.name = "RecordingError";
  }
}

export function provenanceOf(bundle: RecordedBundle): Provenance {
  if (bundle._recording && bundle._recording.real_model_output === true) {
    return "real_model_output";
  }
  if (bundle._fixture && bundle._fixture.synthetic === true) return "synthetic_fixture";
  return "unknown";
}

/**
 * The recording's summary. Real recordings carry a `recording` section; the
 * synthetic fixture carries `modes.recordings`. When neither has it, the
 * summary is built from the run itself.
 */
export function summaryOf(bundle: RecordedBundle): RecordingSummary {
  if (bundle.recording && typeof bundle.recording.recording_id === "string") {
    return bundle.recording;
  }
  const list = bundle.modes?.recordings ?? [];
  const match =
    list.find((r) => r.recording_id === bundle.run.recording_id) ?? (list.length ? list[0] : null);
  if (match) return match;
  return {
    recording_id: bundle.run.recording_id ?? bundle.run.run_id,
    title: bundle.run.goal,
    goal: bundle.run.goal,
    simulated_case: bundle.run.simulated_case,
    spent_usd: bundle.run.spent_usd,
  };
}

/** One verified and one withdrawn claim, for the landing hero. Null without a diagnosis. */
export function excerptOf(bundle: RecordedBundle): RunExcerpt | null {
  const diagnosis = bundle.package?.diagnosis;
  const check = bundle.package?.evidence_check;
  if (!diagnosis || !check || !Array.isArray(diagnosis.claims)) return null;
  const byId = new Map(check.claims.map((c) => [c.claim_id, c]));
  let verified: ClaimExcerpt | null = null;
  let withdrawn: ClaimExcerpt | null = null;
  for (const claim of diagnosis.claims) {
    const result = byId.get(claim.claim_id);
    if (!result) continue;
    const citations = claim.citations ?? [];
    if (result.supported && !verified) {
      verified = { text: claim.text, citation: citations[0] ?? null, reason: "ok" };
    } else if (!result.supported && !withdrawn) {
      const reasons = result.citation_reasons ?? [];
      const failing = reasons.findIndex((r) => r !== "ok");
      withdrawn = {
        text: claim.text,
        citation: (failing >= 0 ? citations[failing] : citations[0]) ?? null,
        reason: result.reason,
      };
    }
  }
  if (!verified && !withdrawn) return null;
  return { verified, withdrawn };
}

/** Check the parts of the bundle the app relies on. Throws a readable error otherwise. */
export function validateBundle(data: unknown): RecordedBundle {
  if (!data || typeof data !== "object") {
    throw new RecordingError("invalid", `${BUNDLE_FILE} is not a JSON object.`);
  }
  const bundle = data as RecordedBundle;
  const run = bundle.run;
  if (!run || typeof run !== "object" || typeof run.run_id !== "string") {
    throw new RecordingError("invalid", `${BUNDLE_FILE} has no "run" section.`);
  }
  if (!isMoney(run.spent_usd) || !run.caps || !isMoney(run.caps.run_usd)) {
    throw new RecordingError(
      "invalid",
      `${BUNDLE_FILE} has money that is not a six-decimal string in "run".`,
    );
  }
  return bundle;
}

export function indexEntryOf(folder: string, bundle: RecordedBundle): IndexEntry {
  return {
    folder,
    summary: summaryOf(bundle),
    provenance: provenanceOf(bundle),
    status: bundle.run.status,
    capUsd: bundle.run.caps?.run_usd ?? null,
    excerpt: excerptOf(bundle),
  };
}

export type FetchLike = (url: string) => Promise<{
  ok: boolean;
  status: number;
  headers?: { get(name: string): string | null };
  json: () => Promise<unknown>;
}>;

async function fetchJson(fetchFn: FetchLike, url: string, label: string): Promise<unknown> {
  let response;
  try {
    response = await fetchFn(url);
  } catch {
    throw new RecordingError("network", `Could not download ${label}.`);
  }
  if (response.status === 404) {
    throw new RecordingError("not_found", `${label} was not found.`);
  }
  if (!response.ok) {
    throw new RecordingError("network", `Downloading ${label} failed (HTTP ${response.status}).`);
  }
  // A static host or dev server that falls back to index.html answers 200 with HTML.
  const type = response.headers?.get("content-type") ?? "";
  if (type.includes("text/html")) {
    throw new RecordingError("not_found", `${label} was not found.`);
  }
  try {
    return await response.json();
  } catch {
    throw new RecordingError("invalid", `${label} is not valid JSON.`);
  }
}

/** Fetch and check both files of a recording folder under `base` (for example "./recordings/"). */
export async function loadRecording(
  folder: string,
  base: string,
  fetchFn: FetchLike,
): Promise<LoadedRecording> {
  if (!FOLDER_RE.test(folder)) {
    throw new RecordingError("invalid_name", "That is not a valid recording name.");
  }
  const root = `${base}${folder}/`;
  const [bundleData, eventsData] = await Promise.all([
    fetchJson(fetchFn, `${root}${BUNDLE_FILE}`, BUNDLE_FILE),
    fetchJson(fetchFn, `${root}${EVENTS_FILE}`, EVENTS_FILE),
  ]);
  const bundle = validateBundle(bundleData);
  let events: TimedEvent[];
  try {
    events = prepareEvents(eventsData);
  } catch (error) {
    throw new RecordingError("invalid", (error as Error).message);
  }
  return { folder, bundle, events };
}

export async function loadIndex(base: string, fetchFn: FetchLike): Promise<RecordingIndex> {
  const data = await fetchJson(fetchFn, `${base}${INDEX_FILE}`, "The list of recordings");
  if (!data || typeof data !== "object" || !Array.isArray((data as RecordingIndex).recordings)) {
    throw new RecordingError("invalid", "The list of recordings is not in the expected shape.");
  }
  return data as RecordingIndex;
}
