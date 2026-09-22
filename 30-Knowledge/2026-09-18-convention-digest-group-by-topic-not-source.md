---
id: 2026-09-18-convention-digest-group-by-topic-not-source
title: Multi-topic digests are grouped by topic
type: convention
area: [writing, deliverables]
projects: []
tags: [digest, roundup, skill-design, reporting, structure, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-18
supersedes: []
---

## What happened

A digest skill pulled items from three sources (email newsletters, a social network, a microblog)
for a brief that spanned several topics on purpose: one topic, and separately two neighbouring ones.
Not every item had to touch every topic. The first run grouped the output by source: a newsletters
section, then one section per network.

The user objected to one item, a story that belonged only to one of the neighbouring topics, sitting
in the newsletters section next to items about the main topic, and asked how it was related to the
main topic at all.

## What was wrong

Not the item: it was exactly what had been asked for. The grouping was wrong. A section organised by
source reads as "everything here is relevant to the same thing", so an item from another topic bucket
looked like an unexplained non sequitur, with nothing saying which bucket it claimed to be in.

## The rule

When a request spans several topics and pulls from several sources, the output has one section per
topic.

- Skip a topic's section entirely when nothing qualifies in that run; never force an empty bucket.
- Before including an item, name the topic it belongs to and check that it really does. An item that
  fits no defined topic is dropped, however good its source.
- The source stays visible on each item, as its citation and link. It just does not organise the
  page.

Grouping by source is the natural first instinct because it mirrors how the data was fetched. It is
the wrong shape whenever the ask covers several topics.

## Links

- [[2026-09-10-convention-report-deliverable-shape]]
