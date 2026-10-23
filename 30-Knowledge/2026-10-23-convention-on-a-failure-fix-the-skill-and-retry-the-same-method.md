---
id: 2026-10-23-convention-on-a-failure-fix-the-skill-and-retry-the-same-method
title: When a skill step fails, fix the skill and retry the same method
type: convention
area: [harness, skills]
projects: []
tags: [skills, failure, retry, fallback, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-23
supersedes: []
---

## The rule

When a step of a skill fails (a generated asset comes out wrong, a check does not pass, a tool call
errors), find the cause, change the skill so the same failure cannot happen again (the prompt it
builds, the check, the rule, the order of steps), and then retry the step with the same method.

Never fall back to a different method on your own: another generator, a simpler version of the
deliverable, dropping the step, or relaxing the check until it passes. Only the user changes the
method the skill plans.

## Why

A fallback hides the failure. The run ends with something that looks finished, the skill keeps the
weakness that caused it, and the next run fails the same way, or quietly ships the weaker version
again. Fixing the skill turns each failure into a permanent improvement, and retrying the same method
shows whether the fix worked.

## How

- Write down the cause in one line before changing anything.
- Put the lesson where it acts: the prompt builder, the gate script, the checklist item. A note that
  nobody reads at that step does not count.
- Retry with the same method and the fixed skill. If it fails again, repeat; if the method itself seems
  wrong, ask the user before changing it.
- Back up the skill before rewriting it
  ([[2026-09-12-convention-back-up-a-skill-before-rewriting-it]]) and sync it afterwards.

## Example

An invented skill renders a short animated clip for a library's events page. One shot comes out with
the book cover mirrored. Wrong: replace that shot with a still image and deliver. Right: add "the
cover text must read left to right" to the shot prompt and a mirrored-text item to the shot check,
then render the same shot again with the same tool.

## Links

- [[2026-09-12-convention-back-up-a-skill-before-rewriting-it]]
- [[2026-10-23-convention-qa-every-generated-image-for-anything-strange]]
