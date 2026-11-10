---
id: 2026-11-08-decision-chrome-restart-only-desktop-chrome-under-chrome-lock
title: "Restart only the desktop Chrome, and only under the chrome lock"
type: decision
area: [harness]
projects: []
tags: [chrome, claude-in-chrome, restart, lock-group, linux]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-11-08
supersedes: []
---

## Decision

`pkill -x chrome` is never used to bring the browser back. It also killed the headless Chrome processes
other tasks had running (card and PDF renders through Playwright) and could break another routine in the
middle of its run.

- `_bin/chrome_restart.py status|check|restart` stops only the desktop Chrome that
  `~/.local/bin/chrome-keepalive.sh` keeps alive on a Linux machine, and waits up to 30 s for the
  keepalive to start a new one. It recognises the desktop process by what it lacks: no `--headless`, no
  `--type=`, no automation flags, no other `--user-data-dir`.
- It refuses with exit 75 while someone else holds the `chrome` lock group, and with exit 3 when no
  keepalive is running, since nothing would bring Chrome back.
- `tasks.py` adds the `chrome` group by itself to every routine whose `agent_args` allow
  `mcp__claude-in-chrome`; `chrome_lock: false` in the front matter opts out (a routine that drives
  another machine's Chrome). `browser_lock.py hold` also takes `chrome`, so an interactive session that
  uses the browser blocks restarts by anyone else and may restart it itself.
- The routine preamble block `browser_restart` (`90-Meta/routines/_preamble/`) tells every browser
  routine to probe, restart through this script up to twice, and then do what the routine says for a
  missing browser.

## Links

- [[2026-11-08-decision-x-linkedin-tasks-share-social-lock-and-wait]]
- [[2026-09-21-reference-where-claude-in-chrome-is-available]]
- [[2026-11-08-decision-shared-routine-preamble-blocks]]
