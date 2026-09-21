---
id: 2026-09-21-reference-where-claude-in-chrome-is-available
title: Where Claude in Chrome is available, per machine, and how to check at run time
type: reference
area: [harness]
projects: []
tags: [chrome, claude-in-chrome, browser, machines, remote-control, headless, reference]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-21
supersedes: []
---

## Per machine

**Each machine has its own Chrome with the Claude extension**, set up once:

- **macOS**: the Chrome you already use, with the extension installed and signed in.
- **Linux**: Chrome under an X desktop (xfce and TigerVNC) that runs as a system unit enabled at
  boot, with Chrome kept alive by a loop the desktop autostarts. Steps are in
  [[2026-09-21-runbook-install-on-a-new-machine]], browser step.

In both cases the extension is paired with `claude --chrome`, and the Remote Control server runs
with `--chrome`, because the `claudeInChromeDefaultEnabled` setting does not reach server mode.

## Browsers are discovered account-wide

`list_connected_browsers` lists every Chrome connected to the same Claude account, not only the
local one. A session on one machine can see, and offer to drive, the Chrome on another. **Pick
the local browser** (`isLocal: true`, and `osPlatform` matching this machine) unless the task
needs a signed-in session that only exists on the other. This matters more when sessions run with
permissions bypassed.

The "Browser 1 / Browser 2" names are not stable across machines or reinstalls. Go by
`osPlatform`, `isLocal` and the device id, never by the name.

## How to check at run time

Do not decide from the OS or the hostname. Probe:

1. If the `mcp__claude-in-chrome__*` tools are not listed at all, not even as deferred tools,
   there is no browser in this session. Skip the browser step and say so.
2. `list_connected_browsers`. An empty list means no extension is connected; say so.
3. A listed browser can still be unreachable (a laptop asleep is listed anyway). Confirm with a
   cheap call such as `tabs_context_mcp`. If it times out twice, stop and tell the user in an
   interactive session, or record "browser not reachable" in a routine and move on.
4. On a Linux machine with no local browser listed, something on the machine is down: check the
   desktop unit's status and the keepalive log.

Never skip a browser source silently: the output says which source was skipped and why.

## Scheduled routines

A routine token from the pool (`claude setup-token`) cannot drive Chrome: Claude Code keeps the
browser off for such tokens even with `--chrome`. Only the CLI's own claude.ai login can. In this
repo's runner a routine has no browser bridge
([[2026-09-15-runbook-brain-routine-auth]]).

The runner does not refuse a routine because its `needs_bridge` names the browser: the run starts
and simply has no browser tools. What turns that into a failure and an alert is the routine
itself. Its body says what it does without the browser and tells it to fail when it cannot do its
job, and a `success_contract` makes a run that did not deliver count as failed, which raises an
alert through the guardian. Separately, while the Claude in Chrome bridge is stale the guardian
warns about every enabled routine whose `needs_bridge` names the browser; it detects and alerts,
it never blocks the run.

## Links

- [[2026-09-21-decision-supported-environments-macos-and-linux]]
- [[2026-09-21-convention-scheduled-task-resources-checked-per-machine]]
