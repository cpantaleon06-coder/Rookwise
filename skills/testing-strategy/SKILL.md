---
name: testing-strategy
description: Design a test strategy and test plan that balances coverage, speed and maintenance.
source_url: https://github.com/anthropics/knowledge-work-plugins/tree/f652327d4e953d7957d99e735c3c7f9964e9d2e5/engineering/skills/testing-strategy
upstream_version_or_commit: engineering 1.2.0 at f652327d4e953d7957d99e735c3c7f9964e9d2e5
license: Apache-2.0
copyright_holder: Anthropic (plugin author; the LICENSE file has no copyright line)
adapted_for: nemotron
roles: [test-planner]
modifications: This file was modified from the original. Replaced the pyramid diagram with a sentence; rewrote the sections as imperative instructions; added a rule that keeps the required output format.
---
Design a test strategy for the system in the task that balances coverage, speed and maintenance.

Follow the testing pyramid: many fast, focused unit tests; some integration tests at medium speed; few slow end-to-end tests that give high confidence.

Match the tests to the component type:

- API endpoints: unit tests for business logic, integration tests for the HTTP layer, contract tests for consumers.
- Data pipelines: input validation, transformation correctness, idempotency tests.
- Frontend: component tests, interaction tests, visual regression, accessibility.
- Infrastructure: smoke tests, chaos engineering, load tests.

Cover business-critical paths, error handling, edge cases, security boundaries and data integrity. Skip trivial getters and setters, framework code and one-off scripts.

Produce a test plan with what to test, the test type for each area, coverage targets and example test cases. Identify gaps in the existing coverage.

Keep the output format the task requires (for example JSON).
