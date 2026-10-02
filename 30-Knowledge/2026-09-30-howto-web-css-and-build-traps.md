---
id: 2026-09-30-howto-web-css-and-build-traps
title: Web CSS and build traps
type: howto
area: [frontend]
projects: []
tags: [css, media-query, specificity, svg, turbopack, worktree, nextjs]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-01
supersedes: []
---

# Web CSS and build traps

Each of these failed silently: no error, no warning, a page that looked fine wherever it was checked
first.

## A paste inside a media query split a selector list

A block of CSS pasted inside a mobile `@media` rule landed in the middle of a selector list:

```css
@media (max-width: 720px) {
  .sidebar > .panel-title,
  .card { padding: 12px; }            /* the pasted block */
  .cards > .panel-title { position: static; }
}
```

That rule existed to undo, on phones, a `position: sticky` set for the desktop two-column layout.
Split in two, its first selector now belonged to the pasted rule, so the heading stayed sticky in the single-column
layout and floated over the content below it while scrolling. Invisible on desktop, invisible in a
diff that only shows added lines, visible only on a phone.

After any edit inside a `@media` block, read the selector lists of the rules around it, and re-check
every rule that resets a desktop-only behaviour (`sticky`, fixed heights, hidden overflow) at the
phone width.

## A scope-nested rule outranks a plain override

A base rule written under a scope, such as `:root:has(body.theme-dark) .tag { color: ... }`,
carries the scope's specificity. A new class that sets its own colour with a plain two-class selector
loses to it and stays the base colour. Override inside the same scope:
`:root:has(body.theme-dark) .tag-active { ... }`.

## An SVG with `--` in a comment is dropped whole

XML forbids `--` inside a comment. An SVG icon whose comment contained one was malformed, and the
browser dropped the whole file, so the favicon was blank. Add a test that fails on `--` inside any
comment in the project's SVG files.

## Turbopack refuses a symlinked `node_modules`

In a git worktree, linking `node_modules` from the main checkout to save an install made Turbopack
refuse to build ("points out of the filesystem root"). Copy the lockfile into the worktree and run
`npm ci` there. For a pure CSS change, it can be faster to skip the local build and inject the
change into the live page from a headless browser
([[2026-09-30-howto-browser-verification-when-the-agent-tab-is-hidden]]).

## Links

- [[2026-08-30-convention-impeccable-craft-floor-rules-for-web]]
- [[2026-08-21-convention-worktree-isolation-per-deliverable]]
- [[2026-09-30-howto-browser-verification-when-the-agent-tab-is-hidden]]
