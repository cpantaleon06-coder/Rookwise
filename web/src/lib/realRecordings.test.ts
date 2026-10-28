// The real recordings published under public/recordings/: each one loads, and its
// optional fields (diagnosis, evidence check, status, coverage) render without errors.
// Rendering uses react-dom/server, so the test needs no browser.

import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { RecordedBanner } from "../run/RunHeader";
import { AuditPanel, CoveragePanel, EvidencePanel } from "../run/Evidence";
import { PackagePanel } from "../run/Outcome";
import { TeamPanel } from "../run/Team";
import { splitOf } from "./incidents";
import { BUNDLE_FILE, EVENTS_FILE, indexEntryOf, provenanceOf, summaryOf, validateBundle } from "./recording";
import { prepareEvents } from "./replay";
import { applyEvents, initialRunState, runStatusLabel } from "./runState";

const PUBLIC = resolve(__dirname, "../../public/recordings");
const folders = readdirSync(PUBLIC, { withFileTypes: true })
  .filter((d) => d.isDirectory())
  .map((d) => d.name)
  .sort();

function load(folder: string) {
  const read = (name: string) => JSON.parse(readFileSync(resolve(PUBLIC, folder, name), "utf8"));
  const bundle = validateBundle(read(BUNDLE_FILE));
  const events = prepareEvents(read(EVENTS_FILE)).map((e) => e.event);
  return { bundle, events, final: applyEvents(initialRunState(), events) };
}

describe("the published recordings", () => {
  it("are the two real runs, and the synthetic fixture is not among them", () => {
    expect(folders).toEqual(["inc-01-run3", "inc-03-run2"]);
    for (const folder of folders) {
      expect(provenanceOf(load(folder).bundle)).toBe("real_model_output");
    }
  });

  it("put a real recording first, so the landing opens it by default", () => {
    // The order of vite.config.ts: real model output first, then the newest.
    const entries = folders.map((f) => indexEntryOf(f, load(f).bundle));
    entries.sort((a, b) => (b.summary.recorded_at ?? "").localeCompare(a.summary.recorded_at ?? ""));
    expect(entries[0].provenance).toBe("real_model_output");
    expect(entries[0].folder).toBe("inc-03-run2");
  });
});

describe.each(folders)("the real recording %s", (folder) => {
  const { bundle, events, final } = load(folder);
  const pkg = bundle.package!;

  it("replays to its recorded end", () => {
    expect(events.length).toBeGreaterThan(0);
    expect(final.terminal).not.toBeNull();
    expect(runStatusLabel(final)).not.toBe("");
  });

  it("does not call the director, managers or auditor hired once the run has ended", () => {
    // The org chart keeps them at "hired"; no event records their final state.
    const html = renderToString(createElement(TeamPanel, { state: final, snapshot: bundle.org!.nodes! }));
    expect(html).not.toContain(">Hired<");
    expect(html).toContain("Final state not recorded");
  });

  it("carries the optional fields", () => {
    expect(pkg.diagnosis?.claims.length).toBeGreaterThan(0);
    expect(pkg.evidence_check?.claims.length).toBe(pkg.diagnosis?.claims.length);
    expect(pkg.diagnosis_status?.status).toBe("audited");
    expect(pkg.coverage?.slices_read).toBeGreaterThan(0);
  });

  it("renders the diagnosis, the evidence check, the status and the coverage", () => {
    const audit = final.audit ?? pkg.audit ?? null;
    const evidence = renderToString(
      createElement(EvidencePanel, {
        pkg,
        revealed: true,
        audit,
        corpusCategory: summaryOf(bundle).category ?? null,
        statusLabel: runStatusLabel(final),
      }),
    );
    expect(evidence).toContain("Root cause");
    expect(evidence).toContain("Audited");
    for (const claim of pkg.diagnosis!.claims) {
      expect(evidence).toContain(claim.claim_id);
    }
    const coverage = renderToString(createElement(CoveragePanel, { coverage: pkg.coverage! }));
    expect(coverage).toContain(`>${pkg.coverage!.slices_read}<`);
    expect(renderToString(createElement(AuditPanel, { audit }))).toContain("Audit");
    expect(renderToString(createElement(PackagePanel, { pkg, partial: true }))).not.toBe("");
  });

  it("says in the banner that the incident is synthetic and a dev incident", () => {
    const summary = summaryOf(bundle);
    expect(splitOf(summary.incident_id)).toBe("dev");
    const banner = renderToString(
      createElement(RecordedBanner, { provenance: provenanceOf(bundle), summary, notice: null }),
    );
    expect(banner).toContain("the incident it investigated is synthetic");
    expect(banner).toContain("development incident, used while tuning");
  });
});
