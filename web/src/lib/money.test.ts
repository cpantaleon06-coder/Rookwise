import { describe, expect, it } from "vitest";
import {
  atLeastPercent,
  formatMicros,
  formatUsd,
  isMoney,
  microsToString,
  percentOf,
  sumMoney,
  toMicros,
  toMicrosOrNull,
} from "./money";

describe("money strings", () => {
  it("accepts exactly six decimals and nothing else", () => {
    expect(isMoney("0.015903")).toBe(true);
    expect(isMoney("12.000000")).toBe(true);
    for (const bad of ["0.01590", "0.0159030", "1e-6", "-0.000001", " 0.000001", "0,000001", "", 0.015903, null]) {
      expect(isMoney(bad)).toBe(false);
    }
  });

  it("parses into whole micro-USD as BigInt", () => {
    expect(toMicros("0.015903")).toBe(15903n);
    expect(toMicros("0.000000")).toBe(0n);
    expect(toMicros("3.000000")).toBe(3_000_000n);
    expect(toMicros("123456789.123456")).toBe(123456789123456n);
    expect(() => toMicros("0.1")).toThrow();
    expect(toMicrosOrNull("nope")).toBeNull();
    expect(toMicrosOrNull(undefined)).toBeNull();
  });

  it("round-trips without loss", () => {
    for (const s of ["0.000001", "0.015903", "0.250000", "9007199254.740993"]) {
      expect(microsToString(toMicros(s))).toBe(s);
    }
    expect(microsToString(-412n)).toBe("-0.000412");
  });

  it("sums exactly where floating point would not", () => {
    // 0.1 + 0.2 in floats is 0.30000000000000004; in micro-USD it is exact.
    expect(microsToString(sumMoney(["0.100000", "0.200000"]))).toBe("0.300000");
    const entries = ["0.004800", "0.000960", "0.000064", "0.000110", "0.000132", "0.000150", "0.000342"];
    expect(microsToString(sumMoney(entries))).toBe("0.006558");
    // Beyond 2^53 micro-USD a Number would round; BigInt does not.
    expect(microsToString(sumMoney(["9007199254.740992", "0.000001"]))).toBe("9007199254.740993");
  });
});

describe("money display", () => {
  it("keeps all six decimals with a dollar sign", () => {
    expect(formatUsd("0.015903")).toBe("$0.015903");
    expect(formatUsd("0.000000")).toBe("$0.000000");
    expect(formatUsd("0.100000")).toBe("$0.100000");
  });

  it("groups thousands in the whole part only", () => {
    expect(formatUsd("1234.500000")).toBe("$1,234.500000");
    expect(formatUsd("1234567.000001")).toBe("$1,234,567.000001");
    expect(formatUsd("999.999999")).toBe("$999.999999");
  });

  it("formats negatives with the sign before the dollar", () => {
    expect(formatMicros(-412n)).toBe("-$0.000412");
    expect(formatMicros(-1_234_000_000n)).toBe("-$1,234.000000");
  });

  it("never guesses on bad input", () => {
    expect(formatUsd(null)).toBe("Not recorded");
    expect(formatUsd(undefined)).toBe("Not recorded");
    expect(formatUsd("0.1")).toBe("Invalid amount (0.1)");
  });
});

describe("percent math in integers", () => {
  it("computes meter widths from micro-USD", () => {
    expect(percentOf(15903n, 250000n)).toBe(6.36);
    expect(percentOf(0n, 250000n)).toBe(0);
    expect(percentOf(250000n, 250000n)).toBe(100);
    expect(percentOf(1n, 0n)).toBe(100);
    expect(percentOf(0n, 0n)).toBe(0);
  });

  it("compares against the 80 percent threshold exactly", () => {
    expect(atLeastPercent(80n, 100n, 80)).toBe(true);
    expect(atLeastPercent(79n, 100n, 80)).toBe(false);
    expect(atLeastPercent(399_999n, 500_000n, 80)).toBe(false);
    expect(atLeastPercent(400_000n, 500_000n, 80)).toBe(true);
  });
});
