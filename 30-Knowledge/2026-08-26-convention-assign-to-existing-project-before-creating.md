---
id: 2026-08-26-convention-assign-to-existing-project-before-creating
title: Assign work to an existing project before creating one
type: convention
area: [memory-system]
projects: []
tags: [projects, areas, graph, retrieval, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The rule

When a conversation or a task starts, first check whether it fits a project that already exists. A new
project is created only when it fits none, and only after confirming with the user.

1. **Search.** `python3 ~/Brain/_bin/query.py "<task terms>"` and the `status: active` notes in
   `10-Projects/`.
2. **If it fits one**, say so and carry on there: "I'm assigning this to project X, correct?" You do not
   have to wait for the answer to start, but you do have to say it.
3. **If it fits none**, propose a name and ask before creating.
4. **If it half fits**, ask. That usually means the existing project's scope is badly defined, or a new
   one is needed. Do not decide it silently.

## Why

A new project for every task fragments memory. Context about one subject ends up in notes that do not
cite each other, and graph retrieval cannot join them because there are no edges. A month later the
information exists but does not come back when it is needed.

## How to tell whether it fits

Work fits a project when it shares the **subject**, not the task. "Write a pitch for the product" and
"archive the product demo recording" are different tasks on the same subject; they belong together.

When a subject accumulates several lines of work, give it an area note in `20-Areas/` as the entry
point, with the projects linked from it.

## Links

- [[2026-09-15-convention-write-shared-notes-through-vw-py]]
