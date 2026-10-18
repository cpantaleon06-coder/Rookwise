// Score a log with Laya, chunk by chunk, for the stage-0 filter experiment (benchmarks/log_filter).
//
// Usage: node score.mjs <log file> <out.json> [--truth truth.json --sample K [--seed S]]
//                       [--limit N] [--single] [--threads N]
//
// The log is split into chunks of whole lines. Each chunk is as many lines as fit the model's
// 512-token window after the question header (counted with the model's own tokenizer); the next
// chunk starts OVERLAP lines before the previous one ended. Line numbers are 1-based, as in
// core/evidence.py, and are what the output reports, so a kept chunk maps back to original lines.
//
// Each scored chunk gets both question forms in one forward pass: `noul` (form C) and a
// two-option `choice` (form C2). Scoring every chunk takes hours on a laptop CPU, so with --truth
// and --sample only the chunks holding a labeled line (evidence or decoy) plus K seeded random
// other chunks are scored. The labels only pick chunks; Laya never sees them.
// --single times each form alone (the cost of a one-question filter) on the first N chunks.
//
// Runs offline from the pinned bundle in .laya-cache (run download.mjs first). Nothing is sent
// anywhere.
import { readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { Laya } from "@receptron/laya";
import { Tokenizer } from "@huggingface/tokenizers";
import { BUNDLE, bundleDir } from "./bundle.mjs";

export const OVERLAP = 2;
const INSTRUCTIONS =
  "Does this log fragment contain evidence of a failure, a risky change or an anomaly relevant to diagnosing an incident?";
export const QUESTIONS = {
  C: { type: "noul", instructions: INSTRUCTIONS },
  C2: {
    type: "choice",
    instructions: INSTRUCTIONS,
    criteria: {
      A: "yes, it shows a failure, a risky change or an anomaly",
      B: "no, it shows only routine operation",
    },
  },
};

function parseArgs(argv) {
  const [log, out, ...rest] = argv;
  if (!log || !out) throw new Error("usage: node score.mjs <log file> <out.json> [options]");
  const opt = (name) => {
    const i = rest.indexOf(name);
    return i >= 0 ? rest[i + 1] : undefined;
  };
  return {
    log,
    out,
    truth: opt("--truth"),
    sample: opt("--sample") !== undefined ? Number(opt("--sample")) : undefined,
    seed: Number(opt("--seed") ?? 20261017),
    limit: opt("--limit") !== undefined ? Number(opt("--limit")) : Infinity,
    single: rest.includes("--single"),
    threads: opt("--threads") !== undefined ? Number(opt("--threads")) : undefined,
  };
}

// Same rule as core/evidence.split_lines: \n, \r\n or \r end a line; a final break adds no line.
function splitLines(text) {
  const lines = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  if (lines.at(-1) === "") lines.pop();
  return lines;
}

/** Chunks of whole lines whose joined text fits `room` tokens. Lines are 1-based. */
function chunk(lines, room, encode) {
  const lineTokens = lines.map((l) => encode(l).length + 1);
  const chunks = [];
  let start = 0;
  while (start < lines.length) {
    let end = start;
    let est = 0;
    // grow by per-line counts, then confirm on the joined text and shrink if needed
    while (end < lines.length && est + lineTokens[end] <= room) est += lineTokens[end++];
    if (end === start) end = start + 1; // one over-long line: Laya truncates it; flagged below
    while (end - start > 1 && encode(lines.slice(start, end).join("\n")).length > room) end--;
    chunks.push({ start: start + 1, end });
    if (end >= lines.length) break;
    start = Math.max(start + 1, end - OVERLAP);
  }
  return chunks;
}

// mulberry32: a small seeded PRNG, so the sample is reproducible
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

async function pick(chunks, args) {
  if (!args.truth) return chunks.map((c, i) => ({ ...c, index: i, why: "all" }));
  const truth = JSON.parse(await readFile(args.truth, "utf8"));
  const labeled = [...truth.evidence, ...truth.decoys].map((e) => e.line);
  const isLabeled = (c) => labeled.some((n) => c.start <= n && n <= c.end);
  const picked = chunks.map((c, i) => ({ ...c, index: i })).filter(isLabeled).map((c) => ({ ...c, why: "label" }));
  const rest = chunks.map((c, i) => ({ ...c, index: i })).filter((c) => !isLabeled(c));
  const rand = rng(args.seed);
  for (let i = rest.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [rest[i], rest[j]] = [rest[j], rest[i]];
  }
  const sampled = rest.slice(0, args.sample ?? rest.length).map((c) => ({ ...c, why: "sample" }));
  return [...picked, ...sampled].sort((x, y) => x.index - y.index);
}

const round = (x, d = 1) => Math.round(x * 10 ** d) / 10 ** d;
const rssMb = () => process.memoryUsage().rss / 2 ** 20;

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const dir = bundleDir();
  const t0 = performance.now();
  const sessionOptions = args.threads ? { intraOpNumThreads: args.threads } : undefined;
  const laya = await Laya.load({ modelDir: dir, sessionOptions });
  const loadMs = performance.now() - t0;
  const read = async (f) => JSON.parse(await readFile(path.join(dir, f), "utf8"));
  const tok = new Tokenizer(await read("tokenizer/tokenizer.json"), await read("tokenizer/tokenizer_config.json"));
  const encode = (t) => tok.encode(t, { add_special_tokens: false }).ids;

  // An empty state costs the header plus the closing [SEP], so the state room is what is left.
  const headerTokens = {};
  for (const [k, q] of Object.entries(QUESTIONS)) {
    headerTokens[k] = (await laya.systemOne("", { [k]: q })).usage.input_tokens;
  }
  const maxLen = laya.config.max_len;
  const room = maxLen - Math.max(...Object.values(headerTokens));

  const lines = splitLines(await readFile(args.log, "utf8"));
  const all = chunk(lines, room, encode);
  const todo = (await pick(all, args)).slice(0, args.limit);
  let peakRss = rssMb();
  const out = [];
  const tRun = performance.now();
  for (const c of todo) {
    const text = lines.slice(c.start - 1, c.end).join("\n");
    const row = { index: c.index, start: c.start, end: c.end, why: c.why, tokens: encode(text).length };
    row.truncated = row.tokens > room;
    if (args.single) {
      for (const [k, q] of Object.entries(QUESTIONS)) {
        const t1 = performance.now();
        const r = await laya.systemOne(text, { [k]: q });
        row[`ms_${k}`] = round(performance.now() - t1);
        row[`p_${k}`] = k === "C" ? r.answers[k].noul : r.answers[k].probabilities.A;
      }
    } else {
      const t1 = performance.now();
      const r = await laya.systemOne(text, QUESTIONS);
      row.p_C = r.answers.C.noul;
      row.p_C2 = r.answers.C2.probabilities.A;
      row.ms = round(performance.now() - t1);
    }
    out.push(row);
    peakRss = Math.max(peakRss, rssMb());
  }
  const runMs = performance.now() - tRun;
  await laya.close();
  const result = {
    note: "Laya chunk scores for a SYNTHETIC log (benchmarks/log_filter). Line numbers are 1-based.",
    log: path.basename(args.log),
    bundle: { repo: BUNDLE.repo, revision: BUNDLE.revision },
    questions: QUESTIONS,
    mode: args.single ? "single (each form timed alone)" : "both forms in one forward pass",
    threads: args.threads ?? "onnxruntime default",
    selection: args.truth ? { labeled_chunks: "all", random_other_chunks: args.sample, seed: args.seed } : "all",
    max_len: maxLen,
    header_tokens: headerTokens,
    state_room_tokens: room,
    overlap_lines: OVERLAP,
    n_lines: lines.length,
    n_chunks_total: all.length,
    n_chunks_scored: out.length,
    load_ms: round(loadMs),
    run_ms: round(runMs),
    ms_per_chunk: round(runMs / Math.max(1, out.length)),
    peak_rss_mb: round(Math.max(peakRss, process.resourceUsage().maxRSS / 1024)),
    machine: {
      cpu: os.cpus()[0]?.model,
      logical_cpus: os.cpus().length,
      ram_gb: round(os.totalmem() / 2 ** 30),
      os: `${os.type()} ${os.release()}`,
      node: process.version,
    },
    all_chunks: all.map((c) => [c.start, c.end]),
    chunks: out,
  };
  await writeFile(args.out, JSON.stringify(result) + "\n");
  const { chunks: _c, all_chunks: _a, questions: _q, ...summary } = result;
  console.log(JSON.stringify(summary));
}

await main();
