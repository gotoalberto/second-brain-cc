---
id: 2026-09-17-convention-a-single-sample-constant-acquires-false-precision
title: Constants derived from a single observation
type: convention
area: [research, writing]
projects: []
tags: [measurement, rounding, methodology, knowledge-base, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-04
supersedes: []
---

## What happened

In an invented example, the combined shrink of a two-stage image export was quoted again and again as
**3.95996%**. The true value was **3.96% exactly** (two 2% downscales in a row): applied to round sizes
they all gave 3.96000, and the odd figure only appeared on one source image whose width did not divide
evenly, where each stage floored away a fraction of a pixel. It was one sample's rounding residue
reported as if it were the ratio, and it had been copied onto several knowledge base pages before anyone
traced it.

The fact that mattered more than its decimals: the downscale was set **per export preset**, not
globally. Different presets showed very different ratios, so no combined constant was safe to hardcode at
all; it had to be read per preset.

## The trap

**A figure derived from a single observation acquires false authority once it is written down with
decimals.** The decimals make it look measured rather than incidental: "3.96%" reads like an
assumption, while "3.95996%" reads like the output of careful work, even though it is the less
general and, here, the wrong one.

- Trace any suspiciously precise constant back to how many samples produced it, especially before it
  becomes a hardcoded default.
- Prefer stating the rule ("two 2% downscales, each floored to a whole pixel") over the observed residue.

## Propagating a correction

A subagent found the error and fixed the entry page, but left the wrong ratio stated as a rule on the other
pages that repeated it. Finding an error is not the same as propagating the correction: every page that
repeats a figure is checked, including the ones not open when the error surfaced
([[2026-08-30-howto-grep-prose-for-stale-designed-numbers]]).

## Links

- [[2026-09-17-convention-re-edit-the-agent-entry-point-as-a-kb-grows]]
- [[2026-09-12-convention-verify-agent-reported-numbers-from-source]]
