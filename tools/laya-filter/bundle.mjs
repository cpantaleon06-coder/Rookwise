// Where the Laya bundle lives. The revision is pinned so results are reproducible.
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

export const BUNDLE = {
  repo: "receptron/laya-onnx",
  // commit of receptron/laya-onnx read on 2026-10-17 (lastModified 2026-10-16)
  revision: "d42786bdff8a7550316339c5fbf8f46caa83ea1b",
  cacheDir: path.join(here, ".laya-cache"),
};

export const bundleDir = () =>
  path.join(BUNDLE.cacheDir, BUNDLE.repo.replace("/", "--"), BUNDLE.revision);
