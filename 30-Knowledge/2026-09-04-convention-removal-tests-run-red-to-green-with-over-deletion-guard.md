---
id: 2026-09-04-convention-removal-tests-run-red-to-green-with-over-deletion-guard
title: Tests for a removal fail before the deletion and carry an over-deletion guard
type: convention
area: [testing]
projects: []
tags: [tdd, removal, deletion, tests, guard, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The rule

For a feature, a test is red before the code exists and green after. For a **deletion**, the test
asserts the thing is gone, so it must be red against the current code and turn green only once the
deletion lands. A removal test that passes before anything was deleted is testing something else,
or nothing.

That alone is not enough. A test that only checks "the deleted thing is gone" passes equally for a
correct, scoped deletion and for deleting far more than intended. Pair every removal test with an
**over-deletion guard**: a test that passes on both sides of the change and asserts that what must
survive still does (other routes still resolve, sibling components still render, the rest of a list
keeps its items). Without the guard, "delete everything" passes the suite.

## Links

- [[2026-08-26-convention-code-development-pipeline]]
