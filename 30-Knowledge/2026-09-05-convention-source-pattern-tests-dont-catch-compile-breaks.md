---
id: 2026-09-05-convention-source-pattern-tests-dont-catch-compile-breaks
title: Source-pattern tests do not prove the file compiles
type: convention
area: [testing]
projects: []
tags: [tests, regex, build, typescript, compile, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## Context

While fixing an unrelated bug, the opening `/**` of a doc comment was deleted by accident, leaving a
broken block comment. Hundreds of tests stayed green, because they opened source files as text and
asserted on regex patterns. The build caught it.

## The rule

A test that reads a source file as text and asserts on strings or regexes is fast and easy to write,
but it only validates the pattern it looks for. It has no model of the language: a broken comment,
an unbalanced brace or invalid syntax all pass, as long as the right substring sits in the right
place.

Do not read a green run of that kind of test as "the file compiles". Only the build or the type
checker proves that. Run the build right after adding or changing such a test, and after any manual
edit near the code it targets, since that is exactly the damage it cannot see.

## Links

- [[2026-08-26-convention-code-development-pipeline]]
- [[2026-08-30-convention-check-the-effect-not-the-exit-code]]
