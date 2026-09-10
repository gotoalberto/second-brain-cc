---
id: 2026-09-10-decision-every-search-finds-and-fixes-broken-links
title: Every search finds and fixes broken links
type: decision
area: [memory-system]
projects: []
tags: [links, graph, retrieval, linkfix, search, decision]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-10
supersedes: []
---

## What was decided

Every search looks for broken `[[links]]` and fixes the ones with a safe fix. It is not a
periodic job and not something an agent has to remember; it is wired into the two places a
search happens:

- `retrieve.py` (every prompt) classifies the whole graph from the index, which takes a few
  milliseconds, and when something can be repaired launches `linkfix.py` detached, so the
  prompt never waits. What has no safe fix is told to the agent inside `<vault-notes>`, once
  per session for each distinct set, so it gets fixed by hand in that session.
- `query.py` (`/recall`) runs `linkfix.py` inline before searching and prints what is left.

## One resolver

`brainlib.LinkResolver` is the only place a `[[target]]` becomes a note: retrieval's graph
expansion, the doctor and linkfix all use it. Before, each place resolved with a bare path
suffix (`path LIKE '%' || target || '.md'`), which was wrong both ways: too loose (a short
link landed on any note whose name happened to end the same way) and too strict (a link by
the frontmatter `id:` resolved to nothing; that was half the broken links).

It resolves, in order: filename; filename without the date; `entity-<target>`; frontmatter
`id:` or `aliases:`; old names from git history (renames and replaced ids); the same slug
with another date; `.md`, spaces or case.

## What linkfix will and will not do

- It rewrites only links that do resolve, to the note's filename. It never guesses: a link
  with no resolution is reported, not pointed somewhere plausible.
- It leaves fenced code, inline code and embeds alone, and puts the note's mtime back so a
  background repair is not credited to whatever session is active.
- Meeting topic links in `15-Meetings/` are topic nodes by convention, and pending
  `[[entity-...]]` participants connect by themselves once the entity exists. Both are
  counted apart, never as broken.

## Search changes made alongside

- Graph expansion ranks neighbours instead of taking the first rows SQLite returns: an
  outgoing link from the hit weighs 2, a backlink 1, each (hit, note) pair counted once,
  then prompt coverage, then decisions first. Ranking by recency was tried and measured worse.
- The FTS tokenizer uses the porter stemmer, so `fails`, `fail` and `failure` are one word.
  The index rebuilds itself once (`index_vault.INDEX_VERSION`).
- Harness messages (`<task-notification>` and similar) are no longer searched. They were
  the most missed terms in the whole log.
- Filler words and glossary entries were added from the real misses in the log, not
  invented.

## Links

- [[2026-09-08-analysis-every-instrument-watches-one-surface-and-reports-on-all-of-them]]
- [[2026-09-08-convention-vault-is-written-in-english]]
