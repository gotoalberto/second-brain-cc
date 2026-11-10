---
id: 2026-11-09-convention-slack-email-documents-no-ai-shape
title: "Chat messages, emails and documents must not have the shape of AI writing"
type: convention
area: [harness, writing]
projects: []
tags: [humanizer, chat, email, documents, emoji, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-11-09
supersedes: []
---

## What happened

A chat post announcing a new version of a document followed a skill's template: an emoji, a bold title,
and five lines summing the document up with lists packed into sentences with semicolons. The text had
gone through humanizer and passed the style check, because neither looked at emoji, bold titles or
length. The reader's verdict was that it looked written by an AI because of the level of detail.

## The rule

It covers every chat post (Slack, Teams and the like), every email to someone else and every document,
whether a routine writes it or a session does.

- No emoji or `:shortcode:` in chat posts, emails or documents. Check and cross marks in verdict
  tables are still fine.
- No bold title line or markdown heading in a chat message or an email.
- A chat message is one to three plain sentences, at most four lines and about 600 characters, with no
  bullets and no list squeezed into a sentence with semicolons. The detail goes in the attached document
  or in a thread.
- The message that carries a document says what it is and, at most, the one thing that changed.
- In chat, every paragraph is followed by a blank line, so paragraphs show apart.

## How to apply

Shape is something a script can check: a sender (or a gate every sender calls) can refuse emoji,
shortcodes, a bold first line and an over-long chat message by channel, the same way it refuses a text
that skipped humanizer. A template inside a skill that asks for an emoji or a bold title is a bug in the
template.

## Links

- [[2026-11-08-convention-every-outgoing-message-through-humanizer]]
- [[2026-09-10-convention-write-like-a-person]]
