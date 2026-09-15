---
id: 2026-09-15-convention-language-per-audience
title: Language per audience
type: convention
area: [writing, language]
projects: []
tags: [language, translation, audience, tickets, chat, reports, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The rule

Each piece of text is written in the language of whoever reads it, and the user sets that language
once per destination.

- **Replies and everything handed to the user** (chat replies, questions, status snapshots, web pages
  and artifacts, proposal tables, summaries of meetings, code or pull requests, reports) go in the
  user's language, item titles and details included, even when those items will later become tickets.
- **Everything published into a shared tool** (an issue tracker, a team chat channel, a shared drive)
  goes in the language that tool's team works in, often English, whatever language the conversation
  or the meeting was in. Write that text at the moment it is published, from the version the user
  approved.
- **The vault is written in English.** [[2026-09-08-convention-vault-is-written-in-english]]
- **Verbatim quotes** keep the language they were said in. **Code identifiers, file paths, pull
  request numbers and product names** stay as they are.
- **Code inside a report stays in its original language** whatever the report's language; only prose
  and comments follow the report.
- **Messages sent in the user's name** go in the language of the recipient or the thread.

## How to apply

- Draft for the user in their language. When the user approves turning a proposal into tickets or a
  post, write the shared-tool text then, in the tool's language.
- Show the exact wording in the other language only if the user asks to review it.
- When a report may be needed in a second language, structure its build so the translation is cheap:
  [[2026-09-10-convention-report-deliverable-shape]].
- Write the destination languages down as a convention note the first time the user states them, so no
  session has to ask again.

## Links

- [[2026-09-08-convention-vault-is-written-in-english]]
- [[2026-09-10-convention-write-like-a-person]]
