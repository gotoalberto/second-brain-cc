---
id: 2026-10-17-convention-email-replies-are-threaded-replies
title: Email replies and follow ups go out as real threaded replies
type: convention
area: [tooling, email]
projects: []
tags: [email, gmail, threading, reply, google-py, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-17
supersedes: []
---

## The rule

Any reply or follow up to an existing email goes out as a real reply in the original thread, never as
a new message with a "Re:" subject and the history pasted underneath:

```sh
python3 ~/Brain/_bin/google.py send --account <name> --reply-to <gmail message id> --to <other party> --body-file answer.html --html
```

`--reply-to` takes the id of the message being answered, for any named account.

## What `--reply-to` does

- **Keeps the thread**: sets the Gmail `threadId`, plus `In-Reply-To` and `References` from the
  original's `Message-ID`, so every mail client files it with the conversation.
- **Keeps the subject**: "Re: <original subject>". A different `--subject` is refused (exit 2):
  changing the subject is what splits a thread in most clients.
- **Builds the quote the way Gmail does**: an attribution line such as
  `On Tue, 3 Mar 2026 at 09:40, Ana Ruiz <ana@example.org> wrote:`, then the original in a
  `gmail_quote` div and a `blockquote` in the HTML part, and `> ` lines in the plain text part.
- **The recipient is the other party**: the sender of the message being answered, or its recipient
  when answering your own message (a follow up). Check `--to` against the original before sending.
- `--attach FILE` (repeatable) works with or without `--reply-to`.

## Why

A follow up built by hand, a new message with "Re:" in front of the subject and the old text pasted
as `> ` lines, has no thread id and no reply headers. Gmail shows it as a separate conversation with
the history as raw text, the recipient sees something that looks like a forwarded fragment, and the
"keep the original subject" rule gets broken again each time someone rebuilds the reply by hand. One
flag that does it all removes the hand building.

## Example

An invented book club organiser answers a member's question about the next meeting: read the inbox,
take the message id of the member's mail, write the answer in `answer.html`, and send it with
`--reply-to <that id>`. The member's client shows it under their own question, quoted below the answer.

## Links

- [[2026-09-23-convention-email-bodies-go-out-as-html-not-plain-text]]
- [[2026-10-14-howto-email-inline-images-with-cid]]
