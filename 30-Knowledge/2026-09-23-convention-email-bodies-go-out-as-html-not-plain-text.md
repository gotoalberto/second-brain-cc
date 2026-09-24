---
id: 2026-09-23-convention-email-bodies-go-out-as-html-not-plain-text
title: Email bodies go out as HTML with a plain text fallback
type: convention
area: [email, brain]
projects: []
tags: [email, gmail, formatting, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-23
supersedes: []
---

## Context

An introduction mail arrived as a tall, narrow column: every paragraph broken at about 70
characters. The text had no hard line breaks. The cause was the composer, which built the body
as a single `text/plain` part; a reading client re-wraps a plain part at its own fixed width. A
`text/html` part with one `<p>` per paragraph is flowed by the client to the window width. The
improvised composer existed because one account had no send command, so every mail meant a
throwaway script.

## Rule

**Never compose a mail by hand with `MIMEText` or a lone `set_content(...)`.** Every mail Brain
sends goes through `_bin/mail_body.py`:

- `build_message(to, subject, body, sender=, cc=, bcc=, html=)` returns a
  `multipart/alternative`: the HTML part is what people see, the plain text stays as the
  fallback. `to`, `cc` and `bcc` take a string or a list.
- `text_to_html(text)` does the conversion. Blank lines separate paragraphs; single newlines
  inside a paragraph are wrapping and are joined so the text can flow. Bullet lines (`-`, `*`,
  `1.`) become a list even under a lead-in line, and a run of short lines (a signature, an
  address) keeps its breaks. A plain body is escaped, so it is data and never markup.

**Write the body as plain text with a blank line between paragraphs**, and do not wrap it
yourself: wrapping is the reader's job.

`google.py send` and the guardian's alert mails both go through `guardian_core/mailer.py`,
which composes with `build_message`; `--html` still means "this body already is markup" and
passes it through as is. Tests: `_bin/mail_body_test.py`.

## Links

- [[2026-09-10-convention-write-like-a-person]]
- [[2026-09-05-convention-read-thread-end-before-outbound-message]]
