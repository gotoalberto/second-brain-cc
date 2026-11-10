---
id: 2026-11-08-decision-generic-skills-no-duplicated-code
title: "Shared capabilities live in generic skills; tasks never copy code or import another task's script"
type: decision
area: [harness, skills]
projects: []
tags: [skills, routines, duplication, architecture]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-11-08
supersedes: []
---

## Rule

- A capability more than one task can use (read or send on a chat service, render a digest email, check
  the send log, read X, read a mailbox) lives in **one** generic skill with its own command line,
  SKILL.md and tests.
- A task (its routine plus its own skill) calls those skills by their commands. Its own script holds
  only what is specific to it: which chats, what counts as a mention, its contract terms, the shape of
  its email.
- Never import another skill's or task's internal module, and never copy a function between scripts.
  When a second task needs a function that lives inside a task, move it into a generic skill first and
  make both call it.
- Before writing a script, list the capabilities it needs and look for the generic skill. If none exists,
  create it first.

## Why

The first versions of two watch routines written the same day each copied the digest render and the
send log check, and one imported a backup task's module just to reach a chat bridge. Three copies of the
same code drift, and a fix lands in one of them.

## How to apply

Every new or changed scheduled task goes through this rule before its first script is written. When an
existing task is touched and still carries a copy, migrate it to the generic skill in the same change.

## Links

- [[2026-09-12-convention-back-up-a-skill-before-rewriting-it]]
