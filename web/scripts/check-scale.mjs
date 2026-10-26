// Reports margin, padding and gap values that are not on the Fibonacci spacing
// scale (docs/DESIGN_DIRECTION.md section 3). It reads the CSS under src/ and the
// Tailwind classes in src/**/*.tsx. It only reports: the exit code is always 0.
//
//   npm run check:scale

import { readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";

const ROOT = resolve(import.meta.dirname, "..");
const SRC = join(ROOT, "src");
const TOKENS = new Set([0, 8, 13, 21, 34, 55, 89, 144]);
const BASE_PX = 4; // Tailwind's --spacing step: p-1 is 4 px.

function files(dir, ext) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((d) => {
    const path = join(dir, d.name);
    if (d.isDirectory()) return files(path, ext);
    return ext.some((e) => d.name.endsWith(e)) && !d.name.includes(".test.") ? [path] : [];
  });
}

const findings = [];

const DECL = /\b(margin|padding|gap|row-gap|column-gap)(-[a-z-]+)?\s*:\s*([^;}]+)/g;
for (const file of files(SRC, [".css"])) {
  readFileSync(file, "utf8")
    .split("\n")
    .forEach((line, i) => {
      for (const m of line.matchAll(DECL)) {
        for (const px of m[3].matchAll(/(-?[\d.]+)px/g)) {
          const value = Math.abs(Number(px[1]));
          if (!TOKENS.has(value)) findings.push([file, i + 1, `${m[1]}${m[2] ?? ""}: ${m[3].trim()}`, value]);
        }
      }
    });
}

const UTIL =
  /(?<![\w[-])(?:[a-z0-9-]+:)*-?((?:m|p)[xytrblse]?|gap(?:-[xy])?|space-[xy])-(\[[^\]\s]+\]|[\d.]+|px)(?![\w.-])/g;
for (const file of files(SRC, [".tsx", ".ts"])) {
  readFileSync(file, "utf8")
    .split("\n")
    .forEach((line, i) => {
      for (const m of line.matchAll(UTIL)) {
        const raw = m[2];
        let value;
        if (raw === "px") value = 1;
        else if (raw.startsWith("[")) {
          const px = /^\[(-?[\d.]+)px\]$/.exec(raw);
          if (!px) continue;
          value = Math.abs(Number(px[1]));
        } else {
          const n = Number(raw);
          value = TOKENS.has(n) ? n : n * BASE_PX;
        }
        if (!TOKENS.has(value)) findings.push([file, i + 1, m[0], value]);
      }
    });
}

if (findings.length === 0) {
  console.log("check:scale: every margin, padding and gap value is on the scale (8, 13, 21, 34, 55, 89, 144).");
} else {
  console.log(`check:scale: ${findings.length} margin, padding or gap values are off the scale:`);
  for (const [file, line, what, value] of findings) {
    console.log(`  ${relative(ROOT, file)}:${line}  ${what}  (${value}px)`);
  }
}
