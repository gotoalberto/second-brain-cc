---
id: 2026-09-25-gotcha-creating-the-legacy-state-dir-hijacks-every-script
title: Creating the legacy state directory moves every script to an empty state
type: gotcha
area: [harness]
projects: []
tags: [state, brain_paths, kp, migration, scripts, gotcha]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-25
supersedes: []
---

# Creating the legacy state directory moves every script to an empty state

## What happened

A new script hard-coded its state directory as the old location, `~/.claude/state/brain`, and called
`os.makedirs` on it. On that machine the state had already been migrated to the new location
(`~/.local/state/brain` on Linux, `~/Library/Application Support/brain` on macOS).

`brain_paths.effective_state_dir()` returns the legacy path whenever it exists as a real directory,
because during a migration splitting the state in two would be worse. So the moment the script
created it, every other script on the machine (`kp.py`, `tasks.py`, the guardian, the hooks) switched
to an empty state directory. The credential cache, the task state and the logs all looked gone, and
the first scheduled run of the new script failed on every step.

## Rule

- **Never write a state path by hand.** Use `brain_paths.effective_state_dir()`, or `brainlib.STATE`
  in a script that already imports brainlib. A test that needs its own state sets `BRAIN_STATE`,
  which wins over both locations.
- **If the legacy directory appears by accident, move it aside** (rename it with a date suffix rather
  than deleting it; it may hold a few minutes of writes from the scripts that followed it). Every
  script resolves back to the right place at once.
- `python3 _bin/brain_paths.py` prints both the configured state directory and the one in use today;
  when they differ on a machine that was already migrated, look for a stray legacy directory.

## Links

- [[2026-09-15-convention-smoke-checks-must-isolate-all-state-not-just-the-input-file]]
- [[2026-08-20-decision-credentials-in-keepass]]
