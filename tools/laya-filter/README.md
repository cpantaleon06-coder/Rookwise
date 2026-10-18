# laya-filter (experiment)

Scores log chunks with [`@receptron/laya`](https://www.npmjs.com/package/@receptron/laya) for the
stage-0 log filter experiment in `benchmarks/log_filter/` (protocol, results and verdict there).
Not part of the product: nothing in `core/` uses it.

```sh
cd tools/laya-filter
npm ci
node download.mjs   # once: about 1.7 GB of ONNX weights into .laya-cache/ (gitignored)
node score.mjs <log> <out.json> [--truth truth.json --sample K] [--limit N] [--single]
```

- The model bundle is pinned to a commit of `receptron/laya-onnx` in `bundle.mjs` and is loaded
  from `.laya-cache/` with no network access after the download.
- Chunks are whole lines that fit the 512-token window after the question header, with a 2-line
  overlap, and keep their original 1-based line numbers.
- Weights are never committed. Licenses: `@receptron/laya` MIT, the Laya weights Apache-2.0
  (Convai Innovations); see `THIRD_PARTY_NOTICES.md`.
