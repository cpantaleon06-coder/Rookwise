---
name: code-review
description: Review a code change for security, performance, correctness and maintainability, and report issues, suggestions and a verdict.
source_url: https://github.com/anthropics/knowledge-work-plugins/tree/f652327d4e953d7957d99e735c3c7f9964e9d2e5/engineering/skills/code-review
upstream_version_or_commit: engineering 1.2.0 at f652327d4e953d7957d99e735c3c7f9964e9d2e5
license: Apache-2.0
copyright_holder: Anthropic (plugin author; the LICENSE file has no copyright line)
adapted_for: nemotron
roles: [code-reviewer]
modifications: This file was modified from the original. Removed the slash command, usage block, connector sections, tips and the markdown report template; kept the review dimensions and turned the report template into a list of contents; added a rule that keeps the required output format.
---
Review the code change given in the task for security, performance, correctness and maintainability.

Check:

- Security: SQL injection, XSS, CSRF; authentication and authorization flaws; secrets or credentials in code; insecure deserialization; path traversal; SSRF.
- Performance: N+1 queries; unnecessary memory allocations; algorithmic complexity (O(n²) in hot paths); missing database indexes; unbounded queries or loops; resource leaks.
- Correctness: edge cases (empty input, null, overflow); race conditions and concurrency issues; error handling and propagation; off-by-one errors; type safety.
- Maintainability: naming clarity; single responsibility; duplication; test coverage; documentation for non-obvious logic.

Report:

- A summary of the change and its overall quality in one or two sentences.
- Critical issues, each with file, line, description and severity.
- Suggestions, each with file, line, description and category (security, performance, correctness or maintainability). Make them actionable, with a code example where it helps.
- Positive observations.
- A verdict: approve, request changes, or needs discussion.

Keep the output format the task requires (for example JSON). The list above names the contents, not a layout.
