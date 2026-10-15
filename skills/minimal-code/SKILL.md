---
name: minimal-code
description: Write the smallest change that solves the whole task, without cutting validation, error handling, security or tests.
source_url: https://github.com/DietrichGebert/ponytail
upstream_version_or_commit: v5.2.0
license: MIT
copyright_holder: DietrichGebert
adapted_for: nemotron
roles: [coder]
modifications: Ported the default (full) level of skills/ponytail/SKILL.md; removed the session and level switching, the slash commands, the other levels and the reply-format instruction; changed grep to find; mapped the closing note to an optional notes field and added a rule that keeps the required output format.
---
Write the smallest change that solves the whole task. The best code is the code never written: solve the whole problem with the least new code.

Before you write, read the task and the code it touches. List every place the change must reach: callers, tests, fixtures, config, exports. Check what the change could break: data it would destroy or expose, callers that stop working. That list is the scope; extra features are not.

Take the first option that does the whole job:

1. Does it need to exist? Skip features, options and flexibility nobody asked for, and name them in one line. A vague request gets the smallest version that does the core job.
2. Is it already in the codebase (a helper, component, service, pattern)? Use it the way the surrounding code does.
3. Does the standard library or a platform feature cover it? Use that, unless the project has its own.
4. Does an installed dependency cover it? Use it. Never add a dependency for a few lines.
5. Can one line do it, readable at a glance? Write one line.
6. Otherwise, write the minimum code that works.

Rules:

- Finish every part the task needs, including the callers, tests and fixtures your change breaks.
- Add no abstraction, wrapper, type conversion, option, config, boilerplate or "for later" code nobody asked for. Keep values in the form the platform gives you. Prefer deleting to adding. Keep the structure the codebase has: its layers, interfaces and conventions.
- The shortest working diff wins once you know everything it must touch. A one-liner that needs decoding is not short.
- Comment only the why that the code cannot show, in one line.
- For a bug fix, find every caller of the function you touch first, then fix the root cause once in the shared code.
- Code you move or merge keeps its error handling and validation.
- Between options of equal size, take the one that is correct on edge cases.
- New non-trivial logic (a branch, a loop, a parser, money or security, a new script) needs one small test or an assert-based self-check. Trivial changes need none.
- Mark a shortcut with a known limit with a comment in this form: `shortcut: <the limit>, <when to upgrade>`.

Never cut validation at trust boundaries, error handling that prevents data loss, security, accessibility, the calibration real hardware needs, or anything the task asked for.

If the output format has a notes field, put one or two lines there on what you skipped or did not check and any risk. Keep the output format the task requires (for example JSON).
