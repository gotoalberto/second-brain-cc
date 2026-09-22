---
id: 2026-09-20-failure-a-guard-can-rot-while-the-rule-it-guards-still-holds
title: Tolerated failing checks and a guard that rotted while its rule held
type: failure
area: [harness, testing]
projects: []
tags: [tests, guards, baseline, technical-debt, failure]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-20
supersedes: []
---

## What happened

Two checks in the vault's test suite had been failing since before a long session started. For
about twelve hours they were used as a baseline, "the same two failures as always", repeated in every
report as if naming them explained them. They were only opened when the user asked what they were.
Both were fixed in ten minutes, and the suite went to zero failures.

Neither was hard. Both had been reclassified, by repetition, from a problem into the weather.

## The first: a guard rotted while its rule held

One check asserted two things about a retrieval script: that an explanatory marker comment was
present, and that a particular filter function was absent. The function was still absent, so the
rule was still obeyed. What had gone was the comment explaining why, and with it the only thing that
would notice if someone brought the filter back. The rule held by inertia while nothing watched it.

The comment was restored and now says the missing part: deleting it re-enables nothing, it only
removes the alarm, which is exactly what had happened unnoticed.

## The second: the check was wrong, not the vault

A check that note folders hold only Markdown flagged four files, all of which belong where they are:
configuration that lives beside the notes in `90-Meta/`, the one folder that is both notes and
machinery. The fix named those four files one by one instead of exempting the folder. Exempting it
would have thrown the check away to silence four known files; with an explicit list, a stray file
there tomorrow still trips it.

An earlier guess about the cause was wrong, and was only corrected because the check's own output
named the files. Reading the failure took less effort than the guess.

## The lesson

- A failing check that is tolerated stops being information. "Pre-existing and unrelated" was true
  and useless, and it survived because it did real work as a baseline for judging new changes.
- A known failure that nobody has read is not known. It is an unknown one with a familiar name. Open
  every standing failure.
- A green check is not proof that a guard still watches something. When a rule holds, check that
  the thing that would notice its breach is still there.

## Links

- [[2026-09-08-analysis-every-instrument-watches-one-surface-and-reports-on-all-of-them]]
- [[2026-08-30-convention-check-the-effect-not-the-exit-code]]
