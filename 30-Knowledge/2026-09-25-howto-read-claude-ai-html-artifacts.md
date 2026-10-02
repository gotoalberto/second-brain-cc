---
id: 2026-09-25-howto-read-claude-ai-html-artifacts
title: Reading a claude.ai HTML artifact link
type: howto
area: [harness]
projects: []
tags: [claude-ai, artifact, browser, chrome, iframe, sandbox]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-25
supersedes: []
---

# Reading a claude.ai HTML artifact link

## Context

Someone shares a `claude.ai/artifact/<id>` link to an HTML artifact and asks for it to be read. It
looks like a shared document, but it behaves like a sandboxed web page, so treat it as a rendering
problem rather than a fetch.

## What does not work

- **Document tools.** It is not a document, and a document read fails with an access error.
- **Text or script tools on the page** (`get_page_text`, `read_page`, running JavaScript in the
  tab). The artifact's HTML renders inside a cross-origin sandboxed frame, which tools on the parent
  page cannot reach.
- **Opening the frame's URL directly.** A top-level navigation to the frame's host redirects back to
  a viewer page instead of showing the content.
- **Wheel scrolling through the browser extension.** It froze the renderer, and every screenshot after
  that timed out.

## What works

In the browser, use the artifact's own in-page navigation links to jump to a section, click once on a
blank part of the content so it has focus, press `space` to page down, and take a screenshot of each
page. Long artifacts read reliably section by section this way.

If the viewer's sandboxing changes, check this procedure again before relying on it.

## Links

- [[2026-09-21-reference-where-claude-in-chrome-is-available]]
- [[2026-09-30-howto-browser-verification-when-the-agent-tab-is-hidden]]
