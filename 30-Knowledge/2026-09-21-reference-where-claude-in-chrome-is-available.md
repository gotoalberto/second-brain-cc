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
updated: 2026-09-22
supersedes: []
---

## Per machine

**Each machine has its own Chrome with the Claude extension**, set up once:

- **macOS**: the Chrome you already use, with the extension installed and signed in.
- **Linux**: Chrome under an X desktop (xfce and TigerVNC) that runs as a system unit enabled at
  boot, with Chrome kept alive by a loop the desktop autostarts. Steps are in
  [[2026-09-21-runbook-install-on-a-new-machine]], browser step.

In both cases the extension is paired with `claude --chrome`, and the Remote Control server runs
with `--chrome`. That flag is what attaches the browser; no setting does (see below).

**Pairing lives in the native messaging host manifest**, not in a Chrome profile:

```
~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.anthropic.claude_code_browser_extension.json   # macOS
~/.config/google-chrome/NativeMessagingHosts/com.anthropic.claude_code_browser_extension.json                     # Linux
```

`machine_caps.py` decides "paired" from that file. The extension itself may sit in a profile
other than `Default`, so an empty `Default/Extensions` folder proves nothing: check the manifest,
or search every profile.

## Browsers are discovered account-wide

`list_connected_browsers` lists every Chrome connected to the same Claude account, not only the
local one. A session on one machine can see, and offer to drive, the Chrome on another. **Pick
the local browser** (`isLocal: true`, and `osPlatform` matching this machine) unless the task
needs a signed-in session that only exists on the other. This matters more when sessions run with
permissions bypassed.

The "Browser 1 / Browser 2" names are not stable across machines or reinstalls. Go by
`osPlatform`, `isLocal` and the device id, never by the name.

## The machine and the session are two questions

| Question | Settled by |
|---|---|
| Can this **machine** use Chrome? | Chrome paired and running, and the Remote Control server started with `--chrome`: the `## This machine` block at session start |
| Do **I, this session**, have the browser? | Are `mcp__claude-in-chrome__*` tools listed? Nothing else |

**The only correct probe for the session is its tool list.** If those tools are listed (deferred
counts: they are callable after loading them), the session has the browser, so use them. If they
are not listed, this session started without `--chrome` and cannot acquire them mid-flight; say
so and offer `claude --chrome --continue`.

Three probes look authoritative and mislead:

- **`claude mcp list`** does not list `claude-in-chrome`, even in a session that has it. It shows
  configured MCP servers; the harness attaches the browser separately.
- **The session start block** describes the machine. It can say "usable" while this session has
  no browser, and both are true at once.
- **`~/.claude.json`** records settings, not what this process got when it started.

**The session start block is a snapshot, not live state.** A session that started before Chrome
was paired keeps reading "NOT paired" at the top of its context for its whole life, while a
fresh run already says "paired". Before telling the user the browser is unusable on this
machine, run `python3 ~/Brain/_bin/machine_caps.py` again instead of trusting the block.

## `--chrome` is a launch flag

The browser tools are attached when the CLI process starts. A session launched without
`--chrome` cannot be fixed from inside: it would have to relaunch itself, and it is the process
that would have to die. The two real options:

1. **The user relaunches** with `claude --chrome --continue`; `--continue` keeps the
   conversation.
2. **Delegate the browser step to a subprocess**, which works from any session:
   ```
   claude --chrome -p "<the whole browser task, self-contained>"
   ```
   Each call is a fresh session with no memory of the parent, so the prompt carries the entire
   task. `timeout` is not installed on macOS by default, so do not wrap the call in it there.

Every entry point has to carry the flag: Remote Control through `remote_control.py`, a terminal
through `claude --chrome`, a routine or `claude -p` through its caller.

**Never conclude a flag is unsupported from `--help` alone.** `--chrome` has been hidden from
`remote-control --help` on a platform where it works, and a setup that grepped the help text
silently dropped the flag, so every app session came up without a browser. That looked exactly
like a missing platform feature. To tell a hidden flag from an absent one, run it and read the
error: `Unknown argument` means absent; any other answer means the parser accepted it.

## What is not the mechanism

All of these have been measured and ruled out; do not spend time on them:

- **The `claudeInChromeDefaultEnabled` setting** (`/chrome`, "Enabled by default"). It has been
  `true` on a machine whose sessions had no browser tools, interactive and `-p` alike, and absent
  on a machine where Chrome always worked. It does not bind the tools, in server mode or out.
- **The Claude Code version**, beyond being recent enough to accept `--chrome`. Upgrading
  changed nothing by itself. Install with the native installer anyway: Homebrew can lag several
  releases behind.
- **A permissions-bypass wrapper** that passes `"$@"` through. With `--chrome` it yields the same
  tools as the plain CLI. A wrapper that drops `"$@"` is a different story: it loses the flag.

After any change to any of this, restart the Remote Control service: the server keeps the flags
it started with.

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
browser off for such tokens even with `--chrome`. Only the CLI's own claude.ai login can.

So a routine whose `--allowedTools` allows `mcp__claude-in-chrome` gets a first attempt **on the
CLI's own login with `--chrome`**, with no pool token in its environment, and its prompt tells
it that the machine's Chrome is where the user's logged-in sessions live. If the CLI is not
logged in on that machine, that attempt fails as an authentication failure and the runner falls
back to the pool token without the browser, raising a warning that says to run
`claude auth login` there. Details in [[2026-09-15-runbook-brain-routine-auth]].

A run that ends up without the browser still starts. What turns that into a failure and an
alert is the routine itself. Its body says what it does without the browser and tells it to fail
when it cannot do its job, and a `success_contract` makes a run that did not deliver count as
failed, which raises an alert through the guardian. Separately, while the Claude in Chrome bridge
is stale the guardian warns about every enabled routine whose `needs_bridge` names the browser;
it detects and alerts, it never blocks the run.

## Links

- [[2026-09-21-decision-supported-environments-macos-and-linux]]
- [[2026-09-21-convention-scheduled-task-resources-checked-per-machine]]
- [[2026-09-12-reference-tool-and-service-catalogue]]
