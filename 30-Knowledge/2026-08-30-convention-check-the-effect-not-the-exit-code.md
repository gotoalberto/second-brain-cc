---
id: 2026-08-30-convention-check-the-effect-not-the-exit-code
title: Check the effect, not the exit code
type: convention
area: [engineering]
projects: []
tags: [verification, shell, exit-code, testing, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-08-30
supersedes: []
---

## The rule

In a chain of commands (`cmd1; cmd2; echo $?` or `cmd1 | cmd2`), the exit code you read is
the last command's, not the one that matters. To check whether `cmd1` worked, run it alone,
or capture `$?` right after it; in a pipe, use `PIPESTATUS` or `set -o pipefail`.

The reliable signal is not the exit code at all, it is the effect on the world. Does the
resource the command was supposed to create exist? Did the file change? Ask about that
state, not about the report the command gives of itself.

## How it went wrong

- A deploy script was run as `./deploy.sh > log 2>&1; echo "exit=$?"; tail -40 log`. It
  printed `exit=0`, which was `tail`'s code. The script had actually exited non-zero when
  the cloud call failed, and the agent was about to report that the script "lied".
- A test run and a `git commit` were chained with `&&`, the last lines of the output were
  read with `tail` and looked fine. They were a fragment of a compilation error, and the
  commit went through because `tail` returned 0.

## Corollaries

- `grep`, `tail` and `head` return 0 even when what they show is an error. Reading a log's
  last lines is not reading its result; look for the word that signals success or failure,
  or check the effect.
- Do not chain `git commit` behind a check whose result you have not read.

## Links

- [[2026-09-05-failure-worktree-shared-agent-git-add-dash-a]]
- [[2026-09-09-convention-memory-must-not-assert-mutable-state]]
