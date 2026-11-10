---
id: 2026-11-08-convention-every-outgoing-message-through-humanizer
title: "Every message sent as the user goes through humanizer and the style check first"
type: convention
area: [harness, writing]
projects: []
tags: [humanizer, style-check, messages, email, chat, social, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-11-08
supersedes: []
---

## Rule

Every text that goes out in the user's name (an email to someone else, a chat message, a post, a reply,
a comment, a document) goes through two steps before it is sent, typed or published:

1. The `humanizer` skill, in embedded mode, on the final text only. It changes wording, never facts,
   numbers, names or links.
2. `python3 _bin/style_check.py <file>`, and a rewrite of whatever it flags (dashes, AI tells,
   headline titles).

The house rules win where they are stricter than humanizer: no dashes at all, and the calling skill's
voice and format. Text the user dictates goes out as given, but still takes the check; a verbatim quote
or a name that needs a dash is the only exception, and is said so.

## How to apply

- **Script senders** (a mail script, a chat script): the cleanest form is a flag such as
  `--humanized` that the sender requires for a real send, plus the style check inside the sender, so a
  text that skipped the pass is refused instead of trusted.
- **Browser senders** (X, LinkedIn and anything typed into a page): write the text to a file, run
  humanizer, run the style check, and type exactly that file only when it passes.
- **Routines**: the `humanizer` block of the routine preamble puts this rule in front of every routine
  prompt ([[2026-11-08-decision-shared-routine-preamble-blocks]]).

## Why

A rule that lives only in prose is skipped on the busy day. Every channel that sends as the user is
public in some way, and a message that reads as written by a machine costs more than the minute the
check takes.

## Links

- [[2026-09-10-convention-write-like-a-person]]
- [[2026-11-09-convention-slack-email-documents-no-ai-shape]]
