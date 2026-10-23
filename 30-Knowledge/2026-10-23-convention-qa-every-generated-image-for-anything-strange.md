---
id: 2026-10-23-convention-qa-every-generated-image-for-anything-strange
title: Check every generated image, frame or clip for anything strange, tracing each limb and prop
type: convention
area: [harness, images]
projects: []
tags: [images, video, generated-media, qa, review, checklist, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-23
supersedes: []
---

## The rule

Before accepting any generated image, video frame, clip or rendered shot, ask one open question beyond
the item checklist: is there anything strange here to fix? Answer it in writing, saying what was looked
at, never with a bare "pass".

## How to look

- **Trace every limb and prop to both ends.** Each arm, leg, hand, rope, cable and handle starts on a
  body or an anchor and ends somewhere that makes physical sense, or leaves the frame.
- **Look for the usual defects**: parts cut off, floating, doubled or missing; objects sunk into floors
  or walls; wrong sizes; poses or loads against physics; text mirrored or garbled.
- **Judge faces and small details on crops at full size**, beside the reference when there is one.
  A contact sheet of thumbnails hides exactly the defects that matter.
- **Anything noticed is a fail to fix**, never "accepted with a note". Fix it through the skill
  ([[2026-10-23-convention-on-a-failure-fix-the-skill-and-retry-the-same-method]]).

## Why

A checklist only finds what it names. Generated media fails in ways nobody listed: a ladder whose
rungs stop short of one rail can pass the maker and two independent checkers when each of
them only ticks items. The open question, asked every time and answered in writing, is what makes the
reviewer actually look at the whole frame.

## In a skill

Make the question a gate item, for example `anything_strange_to_fix`, that only accepts
`pass: <what was looked at>`, next to a `limbs_and_props_attached` item. A gate script that refuses a
bare pass keeps the habit when the reviewer is a model.

## Example

An invented poster for a gym's climbing night shows a climber on a rope. The checklist passes (logo,
date, colours), but tracing the rope shows it ends in mid air with no anchor above. The poster is
regenerated with "the rope runs up to a visible anchor at the top" in the prompt.

## Links

- [[2026-10-07-convention-image-generation-through-chatgpt-image]]
- [[2026-08-24-convention-local-ocr-to-audit-text-in-images]]
