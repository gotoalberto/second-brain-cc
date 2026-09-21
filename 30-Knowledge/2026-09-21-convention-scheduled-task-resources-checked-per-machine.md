---
id: 2026-09-21-convention-scheduled-task-resources-checked-per-machine
title: A scheduled task only runs on a machine that has every resource it needs
type: convention
area: [harness]
projects: []
tags: [scheduled-tasks, routines, machines, preflight, repos, tools, policy, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-21
supersedes: []
---

## The rule

**A scheduled task is not moved to, or enabled on, a machine until its resources are there and
checked on that machine.** Repos cloned (with their remotes and hooks), programs installed,
dependencies installed, paths that exist, logins done. "It works on the other machine" says
nothing about this one.

Without the rule, a routine moved to a new machine runs half blind: a repo missing, a program not
installed, a path from the other OS. The model works around each gap, and the failure only shows
up buried inside the report it sends, days later.

## How it is enforced

`_bin/routine_requires.py` is the preflight. It runs:

1. **Before every agent run.** The task runner calls it; if anything is missing the run is
   refused with exit 2 and an alert that lists each gap and its fix (the clone command, the
   program to install).
2. **By hand, whenever a task is moved or installed.** On the target machine, run
   `python3 ~/Brain/_bin/routine_requires.py check 90-Meta/routines/<id>.md` for a routine whose
   row does not name this machine yet, or `routine_requires.py here --fix` for every enabled
   agent task this machine already runs. `--fix` clones missing repos that declare a URL and
   never installs programs. Fix what is left, run it again until every line passes (exit 0; a
   gap is exit 2), and only then change the row's `machine` or `enabled`.

It can also run as a daily `shell` row on each machine (`python3 _bin/routine_requires.py here`),
ahead of the day's tasks, so a gap alerts the night before instead of at run time.

## What it checks

- **Implicitly, from the routine's `agent_args`**: directories given with `--add-dir`, and the
  programs, script paths and working directories named in its `Bash(...)` allowlist. An absolute
  path from another OS is caught here.
- **Explicitly, from the routine's `requires:` frontmatter**, for what the commands do not show:
  repos (a folder that is not a git checkout fails as a repo), programs and paths. The format is
  in `90-Meta/scheduled-tasks.md`.

What no script can check, so do it by hand when moving a task: sites signed in to in the
machine's Chrome, OAuth for MCP servers, entries in the kdbx, and whether the machine's browser
is up ([[2026-09-21-reference-where-claude-in-chrome-is-available]]).

## Writing a routine that moves well

- Portable commands: `~/...` paths and bare program names (`python3`, not an absolute Homebrew
  path).
- Command forms that work on every version of the tool in use across your machines.
- Declare in `requires:` every repo with its clone URL, and every dependency folder a fresh clone
  lacks (such as `node_modules`).

## Links

- [[2026-09-21-runbook-install-on-a-new-machine]]
- [[2026-09-21-decision-supported-environments-macos-and-linux]]
- [[2026-09-15-runbook-brain-routine-auth]]
- [[2026-09-15-runbook-brain-guardian]]
