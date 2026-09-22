---
id: 2026-09-17-convention-re-edit-the-agent-entry-point-as-a-kb-grows
title: Re-edit the agent entry point every time a body of work lands
type: convention
area: [agents, knowledge-base]
projects: []
tags: [agents, knowledge-base, discoverability, agents-md, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-17
supersedes: []
---

## What happened

A repository built as context for AI agents had grown a `kb/` of tens of thousands of tokens and a
long narrative file, far more than an agent reads in one pass. The decisive check was narrower than
measuring size: `AGENTS.md`, the one file every agent reads first, did not mention the task the
repository existed for even once. Its reading paths were still the ones written on the first day.
An agent entering fresh would read the early material and never reach the pages where a full day of
verification lived, with a real risk of reimplementing a bug that had already been found and fixed.

## The rule

A knowledge base for an agent is only worth what the agent can find from its entry point. Adding
pages without updating the entry point makes the corpus bigger and no more useful, and buries the
new knowledge under material the agent reads first and stops at.

Every time a body of work lands (a trap found, a formula pinned, a gap closed), re-edit the entry
file to route to it, in the same change that writes the knowledge. Do not wait for a cleanup pass.
In practice:

- a table of known traps (wrong assumptions, bugs already fixed) with what each one costs, so
  future work does not repeat them;
- reading paths keyed to the tasks the agent will actually be asked to do, not only to the topics
  that existed on day one;
- the verification method for the domain, written as an instruction, so the method is found and
  not only its past results.

The vault follows the same rule: `AGENTS.md` and `90-Meta/PROTOCOL-COMPACT.md` are its entry point,
and a new convention that nothing routes to is a convention no session will find.

## Links

- [[2026-09-17-trap-a-negative-search-result-calcifies-into-a-permanent-fact]]
