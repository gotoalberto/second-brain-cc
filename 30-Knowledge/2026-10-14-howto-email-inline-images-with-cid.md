---
id: 2026-10-14-howto-email-inline-images-with-cid
title: Emailing images inline in the message body with cid references
type: howto
area: [tooling, email]
projects: []
tags: [email, gmail, inline-images, cid, mime, routines, howto]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-14
supersedes: []
---

## Context

A routine that mails images meant to be seen in the message itself (a chart, a card, a preview) needs
them inline in the body. Attachments would make the reader open them one by one.

## What works

A MIME tree of `multipart/alternative` (plain text and HTML) whose HTML part sits inside a
`multipart/related` that also holds the images, each with a `Content-ID`, referenced from the HTML as
`cid:`. Gmail renders those in the body.

```python
from email.message import EmailMessage
from email.utils import make_msgid

msg = EmailMessage()
msg["To"], msg["Subject"] = "members@example.org", "This week's class schedule"
msg.set_content("This week's schedule is in the HTML version of this message.")
cid = make_msgid(domain="example.org")          # "<...@example.org>"
msg.add_alternative(f'<p>This week:</p><img src="cid:{cid[1:-1]}" alt="Class schedule" width="600">',
                    subtype="html")
with open("schedule.png", "rb") as f:
    msg.get_payload()[1].add_related(f.read(), maintype="image", subtype="png", cid=cid)
# base64url encode msg.as_bytes() and send it as the "raw" field of the Gmail API send call
```

- Give each image an `alt` text and a width: some clients block images until the reader allows them.
- Keep the total size modest. Large inline images get the whole message clipped in some clients.

## What does not work

- **`data:` URIs in `<img src>`**: Gmail strips them, and the image is simply missing.
- **Remote `<img src>` pointing at signed, expiring URLs**: the images show today and break once the
  links expire, so every older email in the inbox ends up with broken images. A remote image is
  only safe from a permanent public URL, and then it is the reader's client that decides whether to
  load it.

## Two details for routines

- **Record the send.** A routine whose success contract counts sends must log this message in the
  send log with the run id, exactly as the vault's own sender does; a message built and sent by a
  separate script otherwise counts as nothing sent
  ([[2026-09-15-runbook-brain-routine-auth]], success contracts). Reuse one shared script for inline
  image mail instead of each routine writing its own.
- **Keep the files too.** Store the images through the vault's file store, and put the link in the
  mail only as a secondary pointer.

## Links

- [[2026-09-23-convention-email-bodies-go-out-as-html-not-plain-text]]
- [[2026-10-17-convention-email-replies-are-threaded-replies]]
