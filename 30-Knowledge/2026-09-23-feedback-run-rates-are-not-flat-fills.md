---
id: 2026-09-23-feedback-run-rates-are-not-flat-fills
title: "A monthly cost the user states is a current run rate, never a flat fill over history"
type: convention
area: [finance]
projects: []
tags: [feedback, spreadsheets, finance, assumptions, run-rate]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-23
supersedes: []
---

## Rule

When the user states a monthly figure ("the team's tooling costs 10K a month"), it is the
**current** monthly figure. Write it only to the month it is stated for and ask for the
earlier months. Never back-fill it across the earlier months of a spreadsheet, even when the
neighbouring line (payroll, say) is built that way.

## Context

A stated run rate of $10,000 a month was written flat across six months of a shared finance
sheet, although the cost had only started in the last one. The fill invented tens of thousands
of dollars of spend in a sheet that other people read as actuals, and a note saying how the
figure was built did not undo that.

## How to apply

- A figure given without a period applies from the month it is stated for. Fill that month and
  ask for the rest instead of interpolating.
- If you are asked to fill a range anyway, say in the reply which cells are actuals and which
  are the run rate.
- Before writing numbers into something shared, check them against the source the same way you
  check any other claim.

## Links

- [[2026-09-22-feedback-add-only-what-was-asked-report-dont-fix]]
- [[2026-09-12-convention-verify-agent-reported-numbers-from-source]]
