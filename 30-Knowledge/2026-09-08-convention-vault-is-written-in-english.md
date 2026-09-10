---
id: 2026-09-08-convention-vault-is-written-in-english
title: The vault is written in English
type: convention
area: [memory-system]
projects: []
tags: [language, retrieval, search, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-08
supersedes: []
---

## The rule

Everything in the vault is written in one language, English by default:

| what | rule |
|---|---|
| body | English |
| `title:` | English |
| `tags:`, `area:`, `projects:` | English |
| filename slug | English |
| comments and docstrings in `_bin/` | English |

The user may talk to the agent in another language, and the agent answers in that language.
The note still goes in English.

**The one exception is verbatim quotes.** A transcript line, something a person actually
said, a piece of UI copy under discussion. That is evidence, and translating it destroys it.
Quote it as it was said and write the surrounding sentence in English.

- A short quote goes inline: the English, then the original in parentheses.
- A whole transcript does not go in the note. Appending it makes the note mostly
  non-English, which is what this rule exists to prevent. It goes to the file store
  (`s3v.py put --to <note> --kind material`) and the note keeps the translation and the
  pointer.

Deliberately not English: `GLOSARIO` and `STOP` in `brainlib.py` and `TASK_VERBS` in
`retrieve.py`. Those are read against what the user types, never against the vault.

## Why

Retrieval is lexical. `sanitize_fts` carries a glossary that maps query terms from the
user's language onto English vault terms, and it runs on the query, one way only. So a note
written in another language is not merely inconsistent, it is unreachable:

- an English prompt has nothing to bridge to it, because the bridge only translates into
  English;
- a prompt in the note's own language gets its terms rewritten into English before the
  search, so it misses the note too.

The failure is silent: no error, no warning, the note never comes back.

## How the rule got lost once

A vault was translated to English in one pass, and the rule that should have come out of
that work was never written into the protocol, the compact block injected at startup, or
the note templates. Two weeks later about one note in seven was back in the user's language,
all of them new. A rule that is not in the injected protocol does not exist for the agent.

## Watch out for

- **Never regex-translate a file.** It turns prose into a mix of both languages. For code,
  use Python's `tokenize`, which tells a name from a string from a comment.
- **A rename that compiles is not a rename that works.** Renaming an identifier with
  `tokenize` does not touch string literals that assert on it (a log line, an expected
  message). Run the tests after any rename.
- **The rule only reaches sessions.** Subagents, skills and scheduled tasks that write notes
  need it pasted into their own definitions. See
  [[2026-09-08-failure-scheduled-tasks-write-into-the-vault-unguarded]].

## Links

- [[2026-09-10-convention-write-like-a-person]]
- [[2026-09-10-decision-every-search-finds-and-fixes-broken-links]]
