---
name: test-first-mindset
description: Enforces Test-Driven Development (TDD) or test-immediately principles. Write or suggest tests before or right after implementation, cover edge cases, and aim for high coverage. Apply automatically on new features, bug fixes, refactors and any logic changes.
version: 1.0
---

# Test-First Mindset Skill

You follow a rigorous test-first or test-immediately approach to ensure code quality, reliability and regression safety from the start.

## Core Principles
- Tests are not optional — they are the primary specification of correct behavior
- Prefer Red → Green → Refactor cycle (classic TDD)
- If full TDD is impractical (e.g. UI or exploratory code), write comprehensive tests immediately after the first working version
- Tests must be fast, isolated, deterministic and readable

## Mandatory Practices
1. **Test Coverage Targets**
   - Core business logic / algorithms: 90%+ coverage
   - Edge cases, error paths, invalid inputs: always covered
   - Happy path + sad paths + boundary conditions

2. **Test Types to Use (choose appropriately)**
   - Unit tests (isolated functions/classes)
   - Integration tests (components working together)
   - Property-based / fuzz testing for robustness
   - Snapshot / approval tests for complex outputs (UI, JSON, etc.)

3. **Framework & Style Guidelines**
   - Use language-appropriate testing libraries (pytest, unittest, Jest, vitest, JUnit, etc.)
   - Follow Arrange-Act-Assert (AAA) pattern
   - Clear, descriptive test names (e.g. test_user_cannot_login_with_invalid_password)
   - Mock only what's necessary; prefer real collaborators when fast

4. **Workflow Integration**
   - Before implementing logic → propose or write failing test first
   - After code generation → immediately add missing tests
   - During refactoring → ensure tests stay green and cover before/after behavior
   - On bug reports → write regression test first, then fix

5. **When Tests Are Missing**
   - Explicitly flag: "Tests are missing for this change — high risk of regression"
   - Propose minimal test suite before proceeding
   - Never suggest committing untested logic without warning

## Output Style
- When suggesting code: include test block first or right after implementation
- Use severity levels: Critical if no tests for core logic; High if edge cases missing
- Provide example test code when recommending additions

Activate automatically on: new functions, classes, endpoints, bug fixes, refactors, any non-trivial change.
Combine with code-review and continuous-improvement for full quality loop.