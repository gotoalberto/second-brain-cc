---
id: 2026-09-15-convention-every-artifact-also-as-html-file-to-s3
title: Every published page is also delivered as an HTML file and archived
type: convention
area: [deliverables, storage]
projects: []
tags: [artifacts, html, deliverables, object-storage, archive, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The rule

Whenever a hosted page or artifact is published for the user, deliver both:

1. the link to the published page;
2. the same page as a self-contained HTML file, sent through the agent's file-delivery tool.

And archive that HTML file with the project in object storage, anchored to the project's note:

```sh
python3 ~/Brain/_bin/s3v.py put <page.html> --to <note> --project <slug> --kind entregable \
  --caption "what the page is and which version"
```

Do it on every publish that changes the content, and again at `/save` so the last version is archived.

## Why

A hosted page can change or disappear with the service or account that hosts it. The HTML file is the
durable copy that stays in the conversation history and in the project's record.

## How to apply

- Keep the page source as one self-contained HTML file (inline CSS and JS, web font links only), so the
  file sent, the file archived and the page published are the same thing.
- When a page is republished many times, include the date in the object name so earlier states stay.
- Without object storage configured, still send the file and say it was not archived.

## Links

- [[2026-08-25-convention-deliverables-to-the-vault]]
- [[2026-08-26-decision-file-vault-in-s3]]
- [[2026-08-28-convention-clickable-links-and-send-files]]
