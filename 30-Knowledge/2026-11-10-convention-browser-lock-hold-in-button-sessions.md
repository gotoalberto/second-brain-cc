---
id: 2026-11-10-convention-browser-lock-hold-in-button-sessions
title: "Sessions opened from a link take the browser lock before driving Chrome"
type: convention
area: [harness]
projects: []
tags: [browser-lock, chrome, claude-in-chrome, remote-control]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-11-10
supersedes: []
---

## Rule

Any session that uses `mcp__claude-in-chrome` and was not typed by the user at a keyboard (a session
opened from a link or a button in an email, a Remote Control session started from the phone) takes the
lock first:

```bash
python3 ~/Brain/_bin/browser_lock.py hold --label "<what it is doing>" --forever
```

launched with the Bash tool's `run_in_background`, and runs `browser_lock.py release` at the end.
`--forever` makes it wait as long as another session or a routine holds the browser.

## Why not `nohup` or `&`

`hold` detaches by itself once it has the lock and records the Claude session above it as the owner.
Under `nohup` or `&` that ancestry is lost, and `release` then refuses, as it should for a hold that
looks like someone else's; the holder had to be killed by hand.

## Incident

Two sessions opened from email links drove the same Chrome a few minutes apart, and the second took no
lock. The Claude in Chrome extension answered "not connected" once in the first session and recovered on
the next `tabs_context_mcp`; Chrome itself had not restarted. The likely cause is that the extension's
single connection was taken by the other session. That is an inference, not a proven cause, but the lock
makes the question moot.

## How to apply

Put the rule into whatever builds those sessions' prompts (the link generator), so every new email
carries it; emails already sent keep their old prompts.

## Links

- [[2026-11-08-decision-x-linkedin-tasks-share-social-lock-and-wait]]
- [[2026-11-08-decision-chrome-restart-only-desktop-chrome-under-chrome-lock]]
