---
id: 2026-09-27-convention-user-handoffs-as-one-pasteable-command
title: Handing the user something to run as one pasteable command
type: convention
area: [harness]
projects: []
tags: [handoff, shell, ssh, secrets, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-30
supersedes: []
---

# Handing the user something to run as one pasteable command

## The rule

Anything the user has to run themselves (a script that needs a typed secret, a production
deploy, a permission change the agent cannot make) goes to them as **one line they paste on their own
machine**. The line fetches whatever it needs and runs it, each step chained with `&&`. Never a
numbered list of commands to type one after another.

## Why

Each separate step is a place to make a mistake: a download that created a folder where a file was
expected, a dry run whose output the user had to read before typing the next line, a command run from
the wrong directory. A single chained line either runs end to end or stops at the first failure, and
the user can see the whole thing before pressing enter.

## How to write the line

- **Fetch, then run.** For example
  `ssh agent-box cat /home/agent/work/release.sh > ~/Downloads/release.sh && bash ~/Downloads/release.sh --check`,
  or a `git pull` in the user's clone followed by the script it brings.
- **Remote paths are absolute.** In `ssh host cat ~/x`, the user's local shell expands `~` to their
  own home before ssh sends anything, and the remote side looks in the wrong place. Write the full
  path on the remote machine.
- **Export PATH for tools that are not on the user's login PATH.** A toolchain installed under the
  user's home may be on PATH in the agent's shell and missing in theirs:
  `export PATH="$HOME/.toolchain/bin:$PATH"; cd ~/project && ...`.
- **Secrets flow through the credential store inside the same line**: `kp.py get <entry> --pipe
  '<command>'` hands the value to the command on stdin, so it never appears in the line, the shell
  history or the chat.
- **Check the change carrying the script is merged** (or pushed where the line fetches from) before
  handing the line over; otherwise the file the line expects is not there yet.
- **Rehearse first when the action matters.** Run the dry mode yourself where you can, and give the
  user the real run only once the rehearsal is clean.

## Links

- [[2026-09-21-convention-agents-must-not-run-scripts-needing-human-typed-secrets]]
- [[2026-09-30-howto-grant-claude-code-allow-rules-from-another-machine]]
- [[2026-08-20-decision-credentials-in-keepass]]
