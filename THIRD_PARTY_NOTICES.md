# Third-party notices

Rookwise is MIT licensed (see `LICENSE`). This repository also contains material adapted from the projects below. The full license texts are in `licenses/`. The runtime skills in `skills/` are modified copies; each `SKILL.md` names its source, version, license and modifications in its frontmatter.

## stop-slop

- Source: https://github.com/hardikpandya/stop-slop
- Version: commit `8da1f030185bdfe8471220585162991eaeb970e9`
- License: MIT, full text in `licenses/stop-slop-MIT.txt`
- Copyright line from its LICENSE: "Copyright (c) 2025 Hardik Pandya"
- Files here:
  - `.claude/skills/stop-slop/`: unmodified copy, used at development time, with its own `LICENSE`.
  - `skills/prose-style/SKILL.md`: modified. SKILL.md and two reference files merged into one short instruction set; the examples file, links, author metadata and some list entries dropped; a rule added that keeps facts, quotes and the output format unchanged.

## ponytail

- Source: https://github.com/DietrichGebert/ponytail
- Version: tag `v5.2.0`
- License: MIT, full text in `licenses/ponytail-MIT.txt`
- Copyright line from its LICENSE: "Copyright (c) 2026 DietrichGebert"
- Files here:
  - `skills/minimal-code/SKILL.md`: modified. Ported the default level of `skills/ponytail/SKILL.md`; removed level switching, slash commands, the other levels and the reply-format instruction; mapped the closing note to an optional notes field.

## knowledge-work-plugins (engineering plugin)

- Source: https://github.com/anthropics/knowledge-work-plugins, directory `engineering/`
- Version: engineering plugin 1.2.0, commit `f652327d4e953d7957d99e735c3c7f9964e9d2e5`
- License: Apache License 2.0, full text in `licenses/knowledge-work-plugins-Apache-2.0.txt`
- Copyright line from its LICENSE: none. The file holds the standard Apache-2.0 text with the appendix template unfilled. The plugin manifest names Anthropic as author.
- NOTICE file: none in the repository at that commit, so there is no NOTICE text to carry.
- Files here, all modified (each file says so in its `modifications` field):
  - `skills/code-review/SKILL.md`
  - `skills/testing-strategy/SKILL.md`
  - `skills/debug/SKILL.md`
  - `skills/deploy-checklist/SKILL.md`
- Modifications: removed the slash commands, usage blocks, connector sections, tips and markdown report templates; rewrote the remaining guidance as short instructions; added a rule that keeps the output format.

## incident-io skills

- Source: https://github.com/incident-io/skills, directory `plugins/incident-io/`
- Version: plugin 1.20261014.705, commit `6af50e2e23e9c782b95a456aab5a053550fba3c9`
- License: MIT, full text in `licenses/incident-io-skills-MIT.txt`
- Copyright line from its LICENSE: "Copyright (c) 2026 incident.io"
- Files here, all modified, all placeholders until the ITOps and DevOps use case is final:
  - `skills/incident-triage/SKILL.md`, from `skills/incidents/SKILL.md`, `references/responding.md` and `references/writing.md`
  - `skills/status-update/SKILL.md`, from `skills/incidents/references/writing.md`
  - `skills/postmortem/SKILL.md`, from `skills/postmortem/SKILL.md`
- Modifications: kept only the tool-independent guidance; removed every incident.io tool, account, MCP server, desktop app and channel reference and every step that asks the user; added the rule that demo incidents are simulated and labeled as simulated.

## Laya (experiment dependency, not shipped)

Used only by the stage-0 log filter experiment (`tools/laya-filter/`, results in
`benchmarks/log_filter/`). Installed from npm as a normal dependency; no code or weights from it
are copied into this repository, and `core/` does not use it.

- `@receptron/laya` 0.2.0, https://github.com/receptron/laya. License: MIT, "Copyright (c) 2026
  Receptron" (from the LICENSE in the npm package).
- Model weights: the ONNX export `receptron/laya-onnx` (commit
  `d42786bdff8a7550316339c5fbf8f46caa83ea1b`) of `convaiinnovations/laya` by Convai Innovations,
  downloaded at run time into the gitignored `tools/laya-filter/.laya-cache/`. License:
  Apache-2.0, per both model cards ("Weights are Convai Innovations' and remain under Apache
  2.0").
- Its runtime dependencies, also installed from npm: `onnxruntime-node` 1.30.0 (MIT) and
  `@huggingface/tokenizers` 0.2.0 (Apache-2.0).

## Not used

harness-engineering (https://github.com/vinicius91carvalho/harness-engineering) has no license. No text from it appears in this repository.
