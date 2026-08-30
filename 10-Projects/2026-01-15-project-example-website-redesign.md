---
id: proj-acme-site-redesign
title: Acme Marketing Site Redesign
type: project
area: [marketing]
projects: [acme-site-redesign]
tags: [web, design, example]
status: active
source: agent
provenance: created 2026-01-15 as a sample project note to show the format
updated: 2026-01-15
---

# Acme Marketing Site Redesign

> **This is an example note — delete it once you have real projects.** It exists
> only to show the shape of a project note. Everything below is invented
> ("Acme", "alice") and refers to nothing real. In a live vault this file would
> be created and updated through `python3 _bin/vw.py`, never edited by hand.

Status: active — new homepage and pricing page shipped to staging; blog template
still in review, and analytics tagging not yet wired up.

## What's left
- [ ] Get sign-off on the blog post template from [[entity-alice]]
- [ ] Wire up analytics events on the pricing page CTA
- [ ] Migrate the 40 legacy blog posts into the new template
- [ ] Run the accessibility pass (contrast, focus order, alt text)
- [ ] Redirect the old `/about-us` URLs to `/about`
- [ ] Cut over DNS from staging to production

## Decisions
- Chose a static-site generator over a CMS for the marketing pages — faster
  pages, simpler hosting, and no database to maintain for content that changes
  a few times a month. A CMS was rejected as overkill for this volume.
- Kept the existing brand palette rather than a full rebrand — the redesign is
  about structure and speed, not a new visual identity.

## Links
- Area: [[area-marketing]]
- Owner / reviewer: [[entity-alice]]
