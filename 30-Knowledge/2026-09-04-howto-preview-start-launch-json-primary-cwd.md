---
id: 2026-09-04-howto-preview-start-launch-json-primary-cwd
title: preview_start configuration and launch commands
type: howto
area: [harness, frontend]
projects: []
tags: [preview_start, launch.json, worktree, browser-pane, harness, howto]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-04
supersedes: []
---

Traps with the desktop app's `preview_start` tool, seen while working inside a git worktree:

1. **It reads `.claude/launch.json` from the session's primary working directory**, not from the repo or
   worktree being worked in. A `launch.json` inside the worktree's own `.claude/` had no effect. If a
   worktree needs its own preview configuration, put it where the session's primary directory looks.
2. **An `npx --yes <package>` runtime executable silently never starts**: no log, no listening port, no
   error. A fully resolved executable (`/usr/bin/python3 -m http.server`, an absolute path to the project's
   `node_modules/.bin/next`) works.

When the pane cannot be used at all, a scratch Playwright script on the system browser is the fallback
([[2026-09-30-howto-browser-verification-when-the-agent-tab-is-hidden]]).
