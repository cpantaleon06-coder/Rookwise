/// <reference types="vitest/config" />
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";
import {
  BUNDLE_FILE,
  EVENTS_FILE,
  FOLDER_RE,
  INDEX_FILE,
  indexEntryOf,
  validateBundle,
  type IndexEntry,
  type RecordingIndex,
} from "./src/lib/recording.ts";

const RECORDINGS_DIR = resolve(import.meta.dirname, "public/recordings");

// Lists every folder under public/recordings/ that has both recording files and
// writes recordings/index.json from them, so adding a recording means adding a
// folder. Real model output comes first, then the newest recording.
function buildIndex(log: (message: string) => void): RecordingIndex {
  const entries: IndexEntry[] = [];
  const folders = existsSync(RECORDINGS_DIR)
    ? readdirSync(RECORDINGS_DIR, { withFileTypes: true }).filter((d) => d.isDirectory())
    : [];
  for (const dir of folders) {
    const folder = dir.name;
    const root = join(RECORDINGS_DIR, folder);
    if (!FOLDER_RE.test(folder)) {
      log(`skipped recordings/${folder}: the folder name is not a plain name`);
      continue;
    }
    if (!existsSync(join(root, BUNDLE_FILE)) || !existsSync(join(root, EVENTS_FILE))) {
      log(`skipped recordings/${folder}: it needs ${BUNDLE_FILE} and ${EVENTS_FILE}`);
      continue;
    }
    try {
      const bundle = validateBundle(JSON.parse(readFileSync(join(root, BUNDLE_FILE), "utf8")));
      entries.push(indexEntryOf(folder, bundle));
    } catch (error) {
      log(`skipped recordings/${folder}: ${(error as Error).message}`);
    }
  }
  entries.sort((a, b) => {
    const real = Number(b.provenance === "real_model_output") - Number(a.provenance === "real_model_output");
    if (real !== 0) return real;
    const date = (b.summary.recorded_at ?? "").localeCompare(a.summary.recorded_at ?? "");
    return date !== 0 ? date : a.folder.localeCompare(b.folder);
  });
  return { recordings: entries };
}

function recordingsIndex(): Plugin {
  const path = `recordings/${INDEX_FILE}`;
  return {
    name: "rookwise-recordings-index",
    configureServer(server) {
      server.middlewares.use(`/${path}`, (_req, res) => {
        const index = buildIndex((m) => server.config.logger.warn(m));
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify(index));
      });
    },
    generateBundle() {
      const index = buildIndex((m) => this.warn(m));
      this.emitFile({ type: "asset", fileName: path, source: JSON.stringify(index) });
    },
  };
}

export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss(), recordingsIndex()],
  build: { sourcemap: false },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
