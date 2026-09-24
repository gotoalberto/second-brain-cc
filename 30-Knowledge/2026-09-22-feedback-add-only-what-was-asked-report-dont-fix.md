---
id: 2026-09-22-feedback-add-only-what-was-asked-report-dont-fix
title: "When editing someone else's shared document, add only what was asked and back it up first"
type: convention
area: [collaboration]
projects: []
tags: [feedback, editing, shared-documents, spreadsheets, backup, scope]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-22
supersedes: []
---

## Context

The user asked for one block of figures to be added to a spreadsheet owned by a colleague and
read by a whole team. While reviewing the sheet the agent also corrected several formulas and
fields it thought were wrong. The user's answer was to fix nothing and only add the block; the
unrequested changes had to be reverted cell by cell from a backup.

## Rule

1. **Add only what was asked.** In a document someone else owns, make exactly the requested
   change. Do not correct formulas, formats or fields on your own initiative. A request to
   "review" the document asks for findings, which go back to the user as a list in the reply.
   It is never permission to change the document.
2. **Back up before the first edit.** Before touching a document you do not own, take a
   restore point: a copy of the file, plus a full dump of the data (values, formulas and
   formats) when it is a spreadsheet.

## Why

A shared document carries other people's trust, and that trust is not the agent's to spend.
Each silent fix is a change its owner did not approve and may not notice, and without a clean
restore point it cannot be undone reliably.

## How to apply

On any task that touches a document owned by someone other than the user: back it up, make the
requested change and nothing else, then list any other problems you saw in the reply.

## Links

- [[2026-09-23-feedback-run-rates-are-not-flat-fills]]
- [[2026-09-12-convention-verify-agent-reported-numbers-from-source]]
