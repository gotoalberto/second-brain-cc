---
id: 2026-08-28-convention-clickable-links-and-send-files
title: Clickable links and delivered files
type: convention
area: [communication, deliverables]
projects: []
tags: [links, files, deliverables, chat, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The rule

Anything the user might want to open arrives as a clickable link, and anything they will use arrives as
a file.

- **Local files:** a markdown link whose target is the path relative to the session's working directory,
  optionally with `:line`: `[report-2026-01-15.md](reports/report-2026-01-15.md)`. A bare relative path
  printed in prose is dead text: it is relative to nothing the user can click.
- **Web URLs:** `[label](https://...)`, not a naked URL in a sentence.
- **Vault notes:** the repository URL, never a local vault path.
  [[2026-08-22-convention-note-links-as-github-urls]]
- **Apps the agent started:** the LAN address. [[2026-08-22-convention-app-urls-with-local-ip]]
- **Deliverables:** send the file itself through the agent's file-delivery tool as well as linking it. A
  link the user has to hunt for is worse than the file arriving in front of them. A task that produces a
  file is not finished until the file is in front of the user.

## Why

The working directory is not always what the user expects, and a path printed in prose cannot be opened.
A report written for the user once went unread because it arrived as a bare path.

## Links

- [[2026-08-28-convention-links-must-resolve-and-be-verified-open]]
- [[2026-09-15-convention-every-artifact-also-as-html-file]]
