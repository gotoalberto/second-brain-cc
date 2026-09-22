---
id: 2026-09-17-convention-measuring-candidate-models-against-ground-truth
title: Measuring candidate models against ground truth
type: convention
area: [verification, measurement]
projects: []
tags: [measurement, methodology, testing, precision, probes, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-17
supersedes: []
---

Four lessons from reconstructing an undocumented system's formulas by probing it. They apply to any
work that tests candidate explanations (a formula, a rounding rule, a fee, a model) against a system
that can only be observed from outside.

## A probe that fails to confirm should measure

A probe built to confirm a hypothesis (accept or reject, match or no match) had one uninformative
failure mode: when no candidate matched, it printed "not pinned by any candidate" and the list of
candidates tried, never the system's actual value. That is a dead end, with no number to explain the
miss and nothing to hand to the next attempt.

When confirmation fails and the same oracle can be reused to measure (a binary search on the
accept/reject boundary, for example), measure the real value and report each candidate's signed
delta from it. "Nothing matched" becomes "here is the real number, and here is by how much and in
which direction each candidate missed". The shape of the deltas (a constant offset, a proportional
error, a divergence) is evidence for which family of candidates to try next. It costs more calls, so
run it once matching has failed.

## Test candidates where they disagree

At most inputs, competing conventions give identical results, so a wrong candidate can score well by
luck. A wrong rounding convention matched most probes built from round numbers, and failed outright
once the probe set was filtered to inputs where the candidates actually give different answers.

- Choose or construct probe inputs for making the candidates disagree, not for being clean.
- When a candidate scores partially, group the failures along any structural axis available
  (direction, sign, magnitude) before explaining them with a tuning parameter. A formula that failed
  several cases by small amounts invited tuning its rounding; grouping by direction put every failure
  on one side and exposed the real cause, a swapped label, which tuning would have hidden.

## A constant from one sample must not carry decimals

A rate was quoted for days with spurious decimals when the true value was a round number. The decimals came
from one observation whose input did not divide evenly, and they made an incidental residue look like
a careful measurement. It had been copied onto five pages before anyone traced it. Worse, the real
finding was that the value varied per item, so no single constant was safe to hardcode at all.

Before a suspiciously precise constant becomes a default, ask how many samples produced it. State a
value from one sample as one sample.

## A correction is propagated, not just made

The same wrong figure was fixed on the page where it was noticed and left standing as a rule on four
other pages that repeated it. Finding an error is not the same as correcting it everywhere: search for
every place that repeats the figure and fix them in the same change.

## Links

- [[2026-09-13-analysis-a-negative-result-is-a-claim-about-the-measurement]]
- [[2026-09-17-trap-measurement-artefacts-shaped-like-answers]]
- [[2026-09-12-convention-verify-agent-reported-numbers-from-source]]
