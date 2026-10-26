// The split of each corpus incident (benchmarks/incidents/<id>/ground_truth.json,
// docs/ARCHITECTURE.md "Benchmark design"). Dev incidents were used while tuning;
// test incidents were held out until the engine was frozen.

export type Split = "dev" | "test";

const SPLITS: Record<string, Split> = {
  "inc-01": "dev",
  "inc-02": "test",
  "inc-03": "dev",
  "inc-04": "test",
  "inc-05": "dev",
  "inc-06": "test",
};

/** The incident's split, or null for an incident outside the corpus (or none). */
export function splitOf(incidentId: string | null | undefined): Split | null {
  if (!incidentId) return null;
  return SPLITS[incidentId] ?? null;
}

export const SPLIT_WORDS: Record<Split, string> = {
  dev: "It is a development incident, used while tuning the system.",
  test: "It is a test incident, held out from tuning until the engine was frozen.",
};

export const SPLIT_CHIP: Record<Split, string> = {
  dev: "Dev incident (used while tuning)",
  test: "Test incident (held out)",
};
