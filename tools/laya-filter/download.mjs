// Fetch the Laya ONNX bundle into tools/laya-filter/.laya-cache (gitignored) and report its size.
// Usage: node download.mjs   (prints one JSON line; run once before filter.mjs)
import { stat } from "node:fs/promises";
import path from "node:path";
import { ensureBundle, BUNDLE_FILES } from "@receptron/laya";
import { BUNDLE } from "./bundle.mjs";

const t0 = performance.now();
const dir = await ensureBundle({ repo: BUNDLE.repo, revision: BUNDLE.revision, cacheDir: BUNDLE.cacheDir });
const seconds = (performance.now() - t0) / 1000;
const files = {};
let bytes = 0;
for (const f of BUNDLE_FILES) {
  const size = (await stat(path.join(dir, f))).size;
  files[f] = size;
  bytes += size;
}
console.log(JSON.stringify({ dir, revision: BUNDLE.revision, bytes, files, seconds: Math.round(seconds * 10) / 10 }));
