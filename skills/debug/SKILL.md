---
name: debug
description: Debug a problem in four steps (reproduce, isolate, diagnose, fix) and report the root cause, the fix and how to prevent a regression.
source_url: https://github.com/anthropics/knowledge-work-plugins/tree/f652327d4e953d7957d99e735c3c7f9964e9d2e5/engineering/skills/debug
upstream_version_or_commit: engineering 1.2.0 at f652327d4e953d7957d99e735c3c7f9964e9d2e5
license: Apache-2.0
copyright_holder: Anthropic (plugin author; the LICENSE file has no copyright line)
adapted_for: nemotron
roles: [debugger]
modifications: This file was modified from the original. Removed the slash command, usage block, connector sections, the request for information from the user and the markdown report template; turned the step diagram and two tips into instructions; added a rule that keeps the required output format.
---
Debug the problem in the task in four steps.

1. Reproduce: state the expected and the actual behavior, the exact steps to reproduce, and the scope (when it started, who is affected).
2. Isolate: narrow it down to a component, service or code path. Check recent changes (deploys, config changes, dependencies). Read the logs and error messages in the task.
3. Diagnose: form hypotheses and test them against the evidence. Trace the code path. Find the root cause, not only the symptom.
4. Fix: propose a fix and explain it. Consider side effects and edge cases. Suggest tests that prevent a regression.

Work from the error message text as given, without paraphrasing it. Treat recent deploys, dependency updates and config changes as the first suspects.

Report the reproduction (expected, actual, steps), the root cause, the fix, and prevention (tests to add, guards to put in place).

Keep the output format the task requires (for example JSON).
