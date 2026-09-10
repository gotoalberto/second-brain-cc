---
id: 2026-08-31-convention-verify-plan-claims-about-semantics-before-writing-them
title: Verify a plan's claims about semantics before writing them
type: convention
area: [engineering]
projects: []
tags: [planning, verification, semantics, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-08-31
supersedes: []
---

## The rule

When a plan makes a claim about language semantics (what a construct does under a specific
failure mode) or about who calls whom (which address, caller or identity a constructor,
modifier or access check will see), verify it before writing it down. Do not rely on general
knowledge of "how this usually works". A grep or a throwaway test is cheap; a wrong claim
baked into a plan spreads into everything built from it (the context pack, the
implementation, the review).

If a comment or piece of code in the repo contradicts the plan, **the comment wins**.
Someone wrote it because they hit the real behaviour. A plan is a prediction; the code is a
report from someone who already ran into it.

## How it went wrong

Twice in one session a confident plan was false the moment someone touched the code, and
both times the person who caught it was the implementer:

1. The plan named the wrong caller of a constructor. An auxiliary deployer had been inserted
   between them, and its code said so.
2. The plan assumed an error-handling construct would catch a failure it does not catch. A
   comment in the test suite already documented the real behaviour.

In both cases the right answer was already written in the repository.

## Links

- [[2026-08-30-convention-check-the-effect-not-the-exit-code]]
