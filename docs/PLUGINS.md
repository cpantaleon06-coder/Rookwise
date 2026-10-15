# Development toolchain: Claude Code plugins

Recorded on 2026-10-14. `docs/ARCHITECTURE.md` stays the source of truth; this file covers only the development tools used to build Rookwise. Facts below come from reading each tool's repository at the pinned version. Anything not checked is marked UNVERIFIED.

## Boundary (read first)

- These tools run in Claude Code at development time. The Rookwise runtime (`core/`, Nemotron on Nebius Token Factory) must not depend on any of them: no imports, no calls, no configuration read at runtime.
- `harness-engineering` is a development workflow. It is NOT the Rookwise harness in `core/harness/`, which is our runtime code that calls Nemotron through the budget ledger. The two share a word, nothing else.
- Their cost comes from the Claude plan, not from the Nebius credits. Keep the two budgets separate in all reporting: the ledger, the benchmark and the cost panel count Nebius usage only.
- The public demo must work for judges without accounts or paid services. incident.io data in the demo is simulated and labeled as simulated.
- Before any plugin text is reused inside operator prompts, check its license and record the reuse here. `harness-engineering` has no license, so none of its text may be reused.
- Do not quote the savings claimed by the ponytail project as ours. If we ever report a saving, it must come from our own measurement.

## Setup in this repository

| Tool | How it reaches this project | Pinned version | License | Accounts needed |
|---|---|---|---|---|
| stop-slop | Copied into `.claude/skills/stop-slop/` from `hardikpandya/stop-slop` | commit `8da1f030185bdfe8471220585162991eaeb970e9` | MIT (`LICENSE` kept in the copy) | None |
| ponytail | `.claude/settings.json`: marketplace `ponytail` (GitHub `DietrichGebert/ponytail`), plugin `ponytail@ponytail` | tag `v5.2.0` | MIT | None |
| harness-engineering | `.claude/settings.json`: marketplace `harness-engineering` (GitHub `vinicius91carvalho/harness-engineering`), plugin `harness@harness-engineering` | tag `v3.0.0` (latest is `v3.5.0`) | None: the repository has no license file and GitHub reports no license | Its workers run `claude -p`, billed to the Claude plan |
| engineering | The user's claude.ai account (plugin directory, source `anthropics/knowledge-work-plugins`). Not declared in project settings, by decision on 2026-10-14 | `1.2.0` | Apache-2.0 | Only for the optional connectors |
| incident-io | The user's claude.ai account (plugin directory, source `incident-io/skills`). Not declared in project settings, by decision on 2026-10-14 | `1.20261014.705` | MIT | An incident.io account for its MCP server |

How the project settings take effect (Claude Code docs, settings reference for `extraKnownMarketplaces` and "Require plugins per repository"): Claude Code registers the two marketplaces after each person accepts the workspace trust dialog for this folder, and plugins that a marketplace lists by relative path, as both of these do, then load from the marketplace copy. Whether the desktop app follows exactly this flow on trust is UNVERIFIED. A contributor who wants engineering or incident-io installs them at their own scope: `engineering@knowledge-work-plugins`, `incident-io@incident-io-skills`.

Prerequisites, checked on the development machine on 2026-10-14: Git 2.55, Bash 5.3 and Node.js 22.21 are present. The `claude` CLI is not on PATH and `jq` is not installed. ponytail needs `node` on PATH. harness-engineering needs the `claude` CLI (its workers run `claude -p`) and `jq` (used by its agents and its `init.sh` template), so it cannot run on this machine until both are installed.

To update a pin, read the release diff, then change the `ref` in `.claude/settings.json`.

## stop-slop

- **What it is**: a skill that removes AI writing patterns from prose: filler phrases, formulaic structures, passive voice, vague claims. One skill, no hooks or commands. Author: Hardik Pandya. It also exists in the user's claude.ai account as `anthropic-skills:stop-slop`, with the same content.
- **Phase**: every phase that produces human-facing text, mostly Phase 3 (UI copy) and Phase 5 (README, Devpost description, video script, feedback).
- **When an agent must use it**: before committing any human-facing text: README, Devpost description, video script, `FEEDBACK.md`, UI copy.
- **What it must not do**: change facts, numbers, dates, model IDs, commands or code; touch the VERIFIED, THIRD-PARTY and UNVERIFIED markers; rewrite verbatim quotes such as API error bodies, license text or rule text.

## ponytail

- **What it is**: "lazy senior dev mode": the smallest change that fully solves the task (YAGNI, standard library first, no unrequested abstractions). Six skills: `ponytail`, `ponytail-review`, `ponytail-audit`, `ponytail-debt`, `ponytail-gain`, `ponytail-help`. Three hooks that run `node`: SessionStart (injects the ruleset on startup, resume, clear and compact), SubagentStart (injects it into subagents) and UserPromptSubmit (tracks `/ponytail lite|full|ultra|off`). Default level: full; `PONYTAIL_DEFAULT_MODE` changes it. It keeps its state outside the repository, in `~/.claude/.ponytail-active` and `~/.claude/ponytail-modes/<sha256 of the project path>`, and runs `git ls-files` to build a short repo map at session start. No network calls were found in its hooks. Its commands ship as TOML files; whether Claude Code loads them is UNVERIFIED, and the six skills cover the same names.
- **Why a plugin and not a loose skill**: the SessionStart hook is what activates it in every session. The user reported an independent JetBrains test in which the plain skill never self-activated; that test was not reproduced here.
- **Phase**: Phases 2 to 4, while `core/` is built with Claude Code.
- **When an agent must use it**: it applies on its own in every Claude Code session in this repository once installed. Before committing a change to `core/`, run `/ponytail-review` on the diff.
- **What it must not do**: override a requirement in `docs/ARCHITECTURE.md`; remove validation, error handling, budget reservations, rate-limit handling, schema checks or tests. A `shortcut:` comment is acceptable only when it names its limit and its upgrade path. The numbers shown by `/ponytail-gain` are the ponytail project's benchmark, not ours.
- **web/**: `web/` is built with GLM, so ponytail does not apply there unless that host supports it. ponytail ships rule files for other hosts (for example `AGENTS.md`), but none is set up for `web/`. Note that the project settings enable it for any Claude Code session in this repository, including one that edits `web/`.

## harness-engineering

- **What it is**: a plugin marketplace plus a spec, build, QA and Goal Review workflow. Skills: `planner` (asks one question at a time, opens a localhost spec review, then writes `project_specs.xml`), `setup`, `generator` (claims Work Items, codes in git worktrees, runs QA and integration), `evaluator` (Goal Review), `supervisor`, `learning-loop`, `update-project`, `grilling`, `monorepo-supervisor-ops`, `worktree-git-recovery`. Agents: `initializer`, `coding-agent`, `qa-agent`. No hooks, no commands. Workers run in the background as headless `claude -p` processes; with no `.harness/roles.json`, every phase routes to the host that started it.
- **It is not the Rookwise runtime**: see the boundary above.
- **Phase**: Phases 2 to 5, as the build process for code. Phase 5 is mostly text and video, so it applies there only to remaining code work.
- **When an agent must use it**: for multi-step build work in `core/`, through `planner` then `generator`, once the user approves a run.
- **Rules**:
  - Any spec it generates (`project_specs.xml`, Acceptance Checks, planning decisions) must be derived from `docs/ARCHITECTURE.md` and must never replace it. If they disagree, `docs/ARCHITECTURE.md` wins, and an architecture change goes there first.
  - Keep its tracked files tracked: `project_specs.xml`, `feature_list.json`, `init.sh`, `harness-progress/`, `.harness/projects.json`, `.harness/integration-branch`. Its own docs say that ignoring the journal makes every later `git add` on it fail. Only transient files are ignored (see `.gitignore`). Its runtime state lives inside `.git/` (`harness-control`, `harness-evidence`, `harness-ledger`, `harness-runs`, `harness-locks`, `harness-governor`).
  - Do not create `.harness/roles.json`. Its example routes work to OpenCode, Cursor Agent, Codex and other paid providers, some launched with the sandbox or approvals disabled. It is also listed in `.gitignore`.
  - It commits by itself: the initializer commits on `main` with its own message, and the generator commits on `gen/*` and `plan/*` branches. Run the initializer only with the user's approval. Never push, and never merge a `plan/*` branch into `main` without the user.
  - It creates worktrees outside the repository, next to it: `<repo>-wt-integration` and `<repo>-wt-<project>-<context>`.
  - Do not reuse its text anywhere: it has no license.
- **What it must not do**: replace `docs/ARCHITECTURE.md`, route work to other providers, or become a runtime dependency.
- **Installer**: `install.sh` was downloaded at `v3.0.0` and read, not run. For Claude Code (`--cli claude`) it copies no files: it runs `claude plugin marketplace add https://github.com/vinicius91carvalho/harness-engineering.git` (the default branch, so `--version` does not pin the Claude install) and `claude plugin install harness@harness-engineering --scope project`. It also keeps a temporary clone (deleted on exit) and receipts in `~/.local/share/harness`. Its optional extras, none installed, can edit `~/.claude/settings.json` (status line, shared config), add the Playwright MCP server through `npx @playwright/mcp@latest`, and run further third-party installers (no-mistakes and treehouse through curl piped to sh, crawl4ai through pip). The pinned marketplace entry in `.claude/settings.json` replaces the installer.
- **Why it has no runtime copy**: it has no license, so nothing from it is ported to `skills/`. Rookwise does not need one either. The director plans and predicts cost, operators build one task each, managers check their work, and an auditor reviews the deliverable in a separate context. That loop already covers planning, building and independent QA at runtime, on Nemotron and under the budget ledger.
- **Known issue, UNVERIFIED**: its initializer adds `.harness/` to `.gitignore`, while its planner and generator commit `.harness/projects.json` and `.harness/integration-branch`. If the initializer adds that line, replace it with the specific entries already in `.gitignore`.

## engineering

- **What it is**: Anthropic's engineering plugin. Skills: `code-review`, `testing-strategy`, `debug`, `deploy-checklist`, `documentation`, `architecture` (architecture decision records), `incident-response`, `standup`, `system-design`, `tech-debt`. No commands, agents or hooks. Optional connectors: Slack, Linear, Asana, Atlassian, Notion, GitHub, PagerDuty, Datadog, Google Calendar, Gmail, each needing its own account.
- **Phase**: Phases 2 to 5.
- **When an agent must use it**:
  - `code-review` before committing a change to `core/`.
  - `testing-strategy` when planning a new `core/` module. Every module in `core/` keeps its tests in `tests/`.
  - `debug` for failures that are not obvious.
  - `deploy-checklist` before the Vercel deployment (Phase 3) and before submission (Phase 5).
  - `documentation` for `docs/api.md` and the README.
  - `architecture` for decision records in `docs/adr/`, one per open design decision: store choice, reputation formula, scope of the public live mode, and reasoning mode per role. The first three are listed under "Open decisions" in `docs/ARCHITECTURE.md`; reasoning mode is in its Harness section ("reasoning off is the starting default for operators, to be confirmed by the benchmark"). The measurement questions in that list (reasoning billing, caching, long-output speed, rate-limit counting) are recorded in `docs/HARNESS_RESEARCH.md`, not in decision records. No decision record exists yet.
- **What it must not do**: connect any connector for the demo or the runtime, or put account data in the repository.

## incident-io

- **What it is**: incident.io's plugin. Skills: `incidents`, `on-call`, `postmortem`, `architecture`, `architecture-author`, `telemetry`, `doctor`, `extensions`, `skill-authoring`, `talking-to-the-user`. It bundles the incident.io MCP server (`https://mcp.incident.io/mcp`), which needs an incident.io account.
- **Phase**: Phases 3 and 4, when the agents and the demo cases are built.
- **When an agent must use it**: as a development-time reference for the ITOps and DevOps use case (triage, status updates, postmortems), to inform how demo scenarios and operator roles are modeled.
- **What it must not do**: become a runtime dependency, connect a real incident.io organization to the demo, or put real incident data in the repository. Demo incidents are simulated and labeled as simulated.

## Verification log

- 2026-10-14: sources, versions, components and licenses read from each repository at the pinned version (stop-slop at `8da1f03`, ponytail at `v5.2.0`, harness-engineering at `v3.0.0`) and from the claude.ai plugin directory (engineering `1.2.0`, incident-io `1.20261014.705`).
- ponytail SessionStart hook: declared in `hooks/claude-codex-hooks.json` at `v5.2.0` (matcher `startup|resume|clear|compact`). That the hook is registered and runs is UNVERIFIED until the plugin installs in a new session. To check: the plugin appears in `~/.claude/plugins/installed_plugins.json` and its cache holds `hooks/claude-codex-hooks.json`; after a session starts in this repository, `~/.claude/ponytail-modes/<sha256 of the project path>` exists, which only the hook writes.
