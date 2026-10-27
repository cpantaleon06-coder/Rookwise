import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { toMicros } from "./money";
import { validateBundle } from "./recording";
import { safeguardRows } from "./safeguards";

const bundle = validateBundle(
  JSON.parse(readFileSync(resolve(__dirname, "../../public/recordings/inc-03-run2/recorded_run.json"), "utf8")),
);

describe("safeguardRows", () => {
  it("builds every row from the inc-03-run2 recording", () => {
    const pkg = bundle.package!;
    const rows = safeguardRows(pkg, pkg.audit, {
      spent: toMicros(bundle.run.spent_usd),
      cap: toMicros(bundle.run.caps.run_usd),
      stops: 0,
    });
    expect(rows.map((r) => [r.key, r.value])).toEqual([
      ["withdrawn", "2 of 4"],
      ["reasons", null],
      ["coverage", "60"],
      ["unread", "0"],
      ["audit", "Accepted with a warning"],
      ["budget", "$0.188152 of $0.500000"],
    ]);
    expect(rows[1].details).toEqual([
      "c2: Quote is not in the cited lines (quote_not_found)",
      "c3: Quote is not in the cited lines (quote_not_found)",
    ]);
  });

  it("renders no row for data the recording does not carry", () => {
    expect(safeguardRows(null, null, { spent: null, cap: null, stops: 0 })).toEqual([]);
    const rows = safeguardRows(null, null, { spent: 5n, cap: 10n, stops: 2 });
    expect(rows.map((r) => r.key)).toEqual(["budget"]);
    expect(rows[0].details).toEqual(["2 calls refused on budget"]);
  });
});
