import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { runFacts } from "./facts";
import { validateBundle } from "./recording";
import type { RecordedBundle } from "./types";

function load(folder: string): RecordedBundle {
  const path = resolve(__dirname, "../../public/recordings", folder, "recorded_run.json");
  return validateBundle(JSON.parse(readFileSync(path, "utf8")));
}

describe("runFacts", () => {
  it("reads the inc-03-run2 recording as it is", () => {
    expect(runFacts(load("inc-03-run2"))).toEqual({
      spentUsd: "0.188152",
      capUsd: "0.500000",
      slicesRead: 60,
      emptySlices: 4,
      unreadRanges: 0,
      claims: 4,
      supported: 2,
      withdrawn: 2,
      verifiedClaimId: "c1",
      withdrawnClaimId: "c2",
      withdrawnReason: "quote_not_found",
      auditVerdict: "accepted_with_warning",
      diagnosisStatus: "audited",
      category: "bad_config",
      operators: 67,
    });
  });

  it("leaves out what a recording does not carry", () => {
    const bundle = load("inc-03-run2");
    const bare: RecordedBundle = { ...bundle, package: null, org: undefined };
    const facts = runFacts(bare);
    expect(facts.spentUsd).toBe("0.188152");
    expect(facts.slicesRead).toBeNull();
    expect(facts.verifiedClaimId).toBeNull();
    expect(facts.withdrawnReason).toBeNull();
    expect(facts.operators).toBeNull();
  });
});
