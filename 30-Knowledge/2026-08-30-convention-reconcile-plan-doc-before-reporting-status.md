---
id: 2026-08-30-convention-reconcile-plan-doc-before-reporting-status
title: Reconcile a plan document with reality before reporting status
type: convention
area: [communication, verification]
projects: []
tags: [status, plans, reporting, verification, drift, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The rule

Before answering "what is left" or "what is the status" from a written plan, TODO or findings list,
reconcile that document against the real state (git history, deployed resources, test results), fix the
document, and only then answer with the corrected list.

## Why

Code fails loudly when it is wrong; a plan document is prose nobody checks, so it drifts as work gets
done. A plan once still listed two items as pending that had been finished that same day. A stale item
wastes time twice: once when it is repeated to the user as true, and again if someone redoes it.

An inherited finding needs re-verifying before it is **executed**, not only before it is reported.
Reporting a stale finding wastes a reply; acting on one can make the product worse, as when a layout
"debt" that two measurement passes confirmed turned out, measured properly, to be a deliberate choice.

## How to apply

1. For each item the document claims is pending, check the thing itself: a grep, a deployment check, a
   test run.
2. Update the document's checkmarks and wording to match.
3. Answer with the current list.
4. Then ask what the product needs that nobody wrote down. A fully checked plan can still be missing its
   most important piece, invisible to a checklist audit because it was never on the checklist.

## Links

- [[2026-09-12-convention-verify-agent-reported-numbers-from-source]]
- [[2026-09-09-convention-memory-must-not-assert-mutable-state]]
