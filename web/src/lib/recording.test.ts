import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  excerptOf,
  indexEntryOf,
  loadRecording,
  provenanceOf,
  RecordingError,
  summaryOf,
  validateBundle,
  type FetchLike,
} from "./recording";
import type { RecordedBundle } from "./types";

const ROOT = resolve(__dirname, "../../public/recordings/demo");
const bundleText = readFileSync(resolve(ROOT, "recorded_run.json"), "utf8");
const eventsText = readFileSync(resolve(ROOT, "recorded_run.events.json"), "utf8");
const demo = JSON.parse(bundleText) as RecordedBundle;

function fakeFetch(files: Record<string, string | number>): FetchLike {
  return async (url) => {
    const body = files[url];
    if (body === undefined) return { ok: false, status: 404, json: async () => ({}) };
    if (typeof body === "number") return { ok: false, status: body, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => JSON.parse(body) };
  };
}

// A real recording has a `recording` section, a `_recording` header and the
// fields added on 2026-10-25. This one is made up for the test.
const real: RecordedBundle = {
  _recording: { real_model_output: true, synthetic_corpus: true },
  recording: {
    recording_id: "rec-x",
    title: "Incident x",
    goal: "Investigate.",
    simulated_case: true,
    spent_usd: "0.188152",
    recorded_at: "2026-10-25T22:46:27Z",
    incident_id: "inc-x",
    category: "bad_config",
  },
  run: { ...demo.run, run_id: "run_x", recording_id: "rec-x" },
  package: {
    ...demo.package!,
    diagnosis: {
      root_cause: "A timeout was cut.",
      category: "bad_config",
      claims: [
        {
          claim_id: "c1",
          text: "Withdrawn one",
          citations: [
            { source_id: "a.log", line_start: 1, line_end: 1, quote: "x" },
            { source_id: "a.log", line_start: 9, line_end: 9, quote: "y" },
          ],
        },
        {
          claim_id: "c2",
          text: "Verified one",
          citations: [{ source_id: "d.diff", line_start: 10, line_end: 10, quote: "+ 30" }],
        },
      ],
      root_cause_claim_ids: ["c2"],
      remediation_plan: null,
    },
    evidence_check: {
      claims: [
        { claim_id: "c2", supported: true, reason: "ok", citation_reasons: ["ok"] },
        { claim_id: "c1", supported: false, reason: "quote_not_found", citation_reasons: ["ok", "quote_not_found"] },
      ],
      supported: 1,
      withdrawn: 1,
      withdrawn_by_reason: { quote_not_found: 1 },
    },
  },
};

describe("summaries", () => {
  it("reads the synthetic fixture summary from modes", () => {
    expect(provenanceOf(demo)).toBe("synthetic_fixture");
    expect(summaryOf(demo).recording_id).toBe("rec-demo-bakery-001");
    expect(excerptOf(demo)).toBeNull();
  });

  it("reads a real recording summary from its recording section", () => {
    expect(provenanceOf(real)).toBe("real_model_output");
    const entry = indexEntryOf("inc-x", real);
    expect(entry.summary.incident_id).toBe("inc-x");
    expect(entry.capUsd).toBe("0.250000");
  });

  it("matches claims to checks by claim_id, not by position", () => {
    const excerpt = excerptOf(real)!;
    expect(excerpt.verified?.text).toBe("Verified one");
    expect(excerpt.withdrawn?.text).toBe("Withdrawn one");
    expect(excerpt.withdrawn?.citation?.line_start).toBe(9);
    expect(excerpt.withdrawn?.reason).toBe("quote_not_found");
  });

  it("treats a null package as no package", () => {
    expect(excerptOf({ ...real, package: null })).toBeNull();
  });

  it("builds a summary from the run when no section has one", () => {
    const bare = { run: demo.run } as RecordedBundle;
    expect(summaryOf(bare).title).toBe(demo.run.goal);
    expect(provenanceOf(bare)).toBe("unknown");
  });

  it("refuses a bundle without a run or with float money", () => {
    expect(() => validateBundle({})).toThrow(/no "run"/);
    expect(() => validateBundle({ run: { ...demo.run, spent_usd: 0.015903 } })).toThrow(/six-decimal/);
  });
});

describe("loadRecording", () => {
  const base = "./recordings/";
  const files = {
    "./recordings/demo/recorded_run.json": bundleText,
    "./recordings/demo/recorded_run.events.json": eventsText,
  };

  it("loads any folder with the two file names", async () => {
    const rec = await loadRecording("demo", base, fakeFetch(files));
    expect(rec.bundle.run.run_id).toBe("run_8f2c1a7d4b");
    expect(rec.events).toHaveLength(64);
  });

  it("refuses names that are not plain folder names, before fetching", async () => {
    for (const name of ["../secrets", "a/b", "", ".hidden"]) {
      await expect(loadRecording(name, base, fakeFetch(files))).rejects.toMatchObject({ kind: "invalid_name" });
    }
  });

  it("reports a missing recording, a server error and bad JSON apart", async () => {
    await expect(loadRecording("nope", base, fakeFetch(files))).rejects.toMatchObject({ kind: "not_found" });
    const broken = { ...files, "./recordings/demo/recorded_run.events.json": 500 };
    await expect(loadRecording("demo", base, fakeFetch(broken))).rejects.toMatchObject({ kind: "network" });
    const garbled = { ...files, "./recordings/demo/recorded_run.json": "{not json" };
    const error = await loadRecording("demo", base, fakeFetch(garbled)).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(RecordingError);
    expect((error as RecordingError).kind).toBe("invalid");
  });

  it("reads an HTML fallback page as a missing recording", async () => {
    const htmlFallback: FetchLike = async () => ({
      ok: true,
      status: 200,
      headers: { get: () => "text/html; charset=utf-8" },
      json: async () => {
        throw new Error("not json");
      },
    });
    await expect(loadRecording("demo", base, htmlFallback)).rejects.toMatchObject({ kind: "not_found" });
  });
});
