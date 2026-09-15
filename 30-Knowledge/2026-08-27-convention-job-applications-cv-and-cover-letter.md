---
id: 2026-08-27-convention-job-applications-cv-and-cover-letter
title: Application documents written for the user
type: convention
area: [writing, deliverables]
projects: []
tags: [cv, cover-letter, applications, documents, forms, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The documents

When the user asks for an application for a role, the deliverable is:

- **A CV and a cover letter, always both.** Deliver them as one PDF (letter first, then CV) when the forms
  involved accept a single attachment.
- **In the user's own format**, recorded once as a template the user provides, not a stock template.
- **A section on why this role, tailored to the posting**: name the organization and the role, what about
  this position is the draw and what the user brings, in a few lines. Never generic.
- **Name the most obvious gap plainly, early in the letter**, before the reader goes looking for it. When a
  posting says who the role is not for, answer that criterion honestly.
- **Never invent experience.** If a detail about the user's background, the role or the organization is
  missing, ask.
- **Written like a person**, with no dashes as punctuation. For generated documents, run a check that fails
  on dash characters and their encoded forms before rendering, because a rule written only in template
  documentation gets broken as soon as work speeds up. [[2026-09-10-convention-write-like-a-person]]
- **Check the length and the rendered pages** before delivering; trim by merging short blocks and
  tightening sentences, not by deleting whole points.

## Before uploading

- **The contact details on the documents match the account the form uses.** Many forms take the email from
  the account and do not let it be edited; documents pointing at another address are incoherent.
- **Verify the role's real location and work arrangement before writing anything.**

## Submitting

The agent may fill in the form, every field and upload, and then **stops at the submit button and tells the
user**. Submitting is the user's, on every application. Creating accounts is the user's too. If a form
action is blocked, stop and say so.

## Recording what went out

An application that is not recorded did not happen. Record, once the user confirms it was sent:

- the role, the organization, the date and the channel;
- the documents actually sent, by name and hash, with the files in the files directory;
- **every free-text answer verbatim**, and any email exchanged about the application, because those are the
  sentences that get quoted back later;
- the decisions taken while filling (yes or no answers, fields left blank and why).

## Links

- [[2026-09-15-decision-file-vault-in-a-local-directory]]
- [[2026-08-28-convention-links-must-resolve-and-be-verified-open]]
