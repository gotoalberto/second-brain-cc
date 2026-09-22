---
id: 2026-09-16-convention-talk-to-the-user-in-their-language
title: Talk to the user in their language and keep the vault in English
type: convention
area: [writing, language]
projects: []
tags: [language, conversation, english, protocol, startup-context, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-16
supersedes: []
---

## The rule

Reply to the user in their language, always: whatever language the question arrived in, and whatever
language the code, the note or the document under discussion is written in. If the user writes in
another language and asks about an English note, the answer is in that language. A switch into English because the
material is in English is the usual slip.

Set the user's language once, in `90-Meta/PROTOCOL-COMPACT.md`, so it reaches every session through
the startup context and the generated `AGENTS.md`. It is not a preference to restate per session.

## What it does not change

This rule is about the conversation. What gets stored stays in English: note bodies, `title:`, tags,
filenames, code, identifiers and commit messages, because a note in another language is unreachable
by search ([[2026-09-08-convention-vault-is-written-in-english]]). The two rules do not collide: one
covers what is said to the user, the other what is written down. A verbatim quote stays in the
language it was said in, as always.

Text published into a shared tool follows that tool's working language; see
[[2026-09-15-convention-language-per-audience]].

## Why it lives in the protocol

Anything that must hold in every session belongs in the injected protocol. The startup context is
what a session reads before anything else, and it survives a new session, a `/clear` and a compaction
alike. A preference remembered anywhere else lapses. The protocol has a fixed token budget, so adding
a rule there usually means slimming another bullet, with the detail moved to its note
([[2026-09-10-decision-startup-budget-warns-never-trims]]).

## Links

- [[2026-09-08-convention-vault-is-written-in-english]]
- [[2026-09-15-convention-language-per-audience]]
- [[2026-09-10-convention-write-like-a-person]]
