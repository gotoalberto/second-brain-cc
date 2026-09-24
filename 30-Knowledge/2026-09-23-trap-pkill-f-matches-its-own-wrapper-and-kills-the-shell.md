---
id: 2026-09-23-trap-pkill-f-matches-its-own-wrapper-and-kills-the-shell
title: "pkill -f from an agent's Bash tool matches its own wrapper and kills the shell mid-command"
type: failure
area: [harness]
projects: []
tags: [bash, pkill, pgrep, agent, harness, trap]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-23
supersedes: []
---

# pkill -f matches the agent's own wrapper shell

## What happened

Restarting a local OAuth listener, this looked obviously correct:

```sh
pkill -f "google.py auth" 2>/dev/null; sleep 1
cd ~/Brain && nohup python3 -u _bin/google.py auth --account work > /tmp/gauth.out 2>&1 &
```

It died with **exit 144** and nothing ran. `pkill -f` matches against the full command line of
every process, and the agent's Bash tool runs the whole thing inside one long `/bin/bash -c '...'`
whose command line **contains the pattern**. So `pkill` matched its own wrapper shell and killed
it, along with everything queued after the semicolon.

This is far likelier for an agent than in a person's terminal. A person types `pkill -f foo` on
its own line and there is no wrapper; the agent's command and the thing it wants to kill always
share one command line, so any `pkill -f` whose pattern also appears later in the same command is
a self-kill by construction.

## How to avoid it

**Never `pkill -f` a pattern that appears in the same command.** Find the pid first, in one call,
then kill it by number in the next:

```sh
pgrep -f "_bin/google.py auth"     # prints e.g. 12345
```
```sh
kill 12345
```

Two calls, no pattern matching at kill time, and `pgrep` is safe because it only prints. If it
must be one command, filter the current shell out explicitly:

```sh
for p in $(pgrep -f "PATTERN"); do [ "$p" = "$$" ] || kill "$p"; done
```

Prefer the two-call form: `$$` is only the wrapper when the loop runs in that same shell.

## The worse variant: pgrep -f in a wait loop

The same self-match in a **waiting** loop kills nothing; it simply never ends:

```sh
while pgrep -f "some-routine-20260923T0804" >/dev/null; do sleep 20; done
echo "finished"
```

The routine being waited on finished within minutes. The loop was still running **more than an
hour later**, because `pgrep` kept matching the wrapper shell of the very command holding the
pattern: a process waiting for itself. This is nastier than the `pkill` case because it is silent.
No error, no exit code, just a background task that stays "Running" and a session that believes it
is still waiting on real work. It was noticed only when the user saw the elapsed time in the
background tasks panel and asked.

Same fix, and it matters more here:

```sh
pgrep -f "PATTERN"                              # the pid, captured once while it runs
```
```sh
while kill -0 12346 2>/dev/null; do sleep 20; done   # wait on the NUMBER
```

Better still, do not hand-roll the wait: the harness re-invokes the session when a backgrounded
Bash command exits, so launching the work in the background and letting the notification arrive
beats polling. Use a wait loop only for work the harness cannot see, and then wait on a pid or on a
file the work creates, never on a `-f` pattern.

## Related

Launching a listener that must outlive the call needs `setsid nohup ... < /dev/null &`, or the
background process is torn down with the tool's shell when the call returns.
