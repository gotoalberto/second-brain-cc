---
id: 2026-10-23-decision-sync-never-rebases-on-a-deadline
title: Vault sync never rebases on a deadline
type: decision
area: [harness]
projects: []
tags: [sync, vault_sync, rebase, merge-driver, json, guardian, compass, install]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-23
supersedes: []
---

## Context

A vault synced between two machines can sit mid-rebase for days without anyone noticing. While it
does, that machine sends and receives nothing: local commits pile up unpushed, the other machine's
work never arrives, and both sides keep writing as if they were alone (two machines can hand out the
same "next number" for a record, for example).

The chain that leads there, with an invented example:

1. A JSON state file is written by two machines. Say `10-Projects/2031-03-01-gym-bookings-state.json`,
   updated by a scheduled routine on one machine and by an interactive session on the other. Git's
   line merge cannot merge two edits of one JSON document, so every pull between them conflicts.
2. On one of those conflicts the `rebase --abort` does not complete. If the sync ignores the abort's
   result and reports "rebase aborted" anyway, nobody learns it failed. A pull on the prompt path that
   rebases under a short timeout makes this more likely: a vault far ahead of its remote cannot finish
   a rebase in a few seconds.
3. From then on every sync pass refuses to work on a checkout with a rebase in progress, by design,
   and the only trace is a cached "last run failed" line in the health report.

Two repairs that look reasonable make it worse. Continuing the rebase with a no-op editor commits
the JSON file with the conflict markers inside it. Aborting a rebase that has been open for days resets
the branch and drops every note written on that machine since, because the blocked sync never
committed them. The repair that holds is the one in
[[2026-09-26-runbook-unwedge-the-vault-sync-after-a-stuck-rebase]]: one merge of both histories in a
scratch worktree, pushed, then the abort and a fast forward in the checkout.

## Decisions

- **No rebase on a deadline.** `brainlib.maybe_pull`, which runs on every prompt and at every session
  start, only fetches and fast-forwards. When there are local commits to replay it leaves them to the
  sync daemon, which runs with no deadline. Tests: `_bin/maybe_pull_test.py`.
- **JSON state files merge per key.** `_bin/json_state_merge.py` is a git merge driver: keys from both
  sides are kept, list items appear once each, two spends of one budget are both counted, counters and
  timestamps move forward, and a value only one side changed takes that side. `.gitattributes`
  assigns it to the state files several machines write (`10-Projects/*-state.json`,
  `90-Meta/*-state.json`). Tests: `_bin/json_state_merge_test.py`.
- **The driver is part of the install.** A merge driver lives in `.git/config`, which git does not
  sync, so each machine has to set it. The guardian checks `merge.brain-json-state.driver` and repairs
  it on every scheduled `repair`, and the install runs `guardian.py repair --git-only` before the first
  sync ([[2026-09-21-runbook-install-on-a-new-machine]]).
- **The abort is checked.** `vault_sync.abort_rebase` retries and reports a failure as a failure. A
  rebase the sync starts leaves a marker, `.git/brain-sync-rebase`, with its pid and start time. When a
  later pass finds a marked rebase older than 20 minutes, with its process gone and no git running, it
  saves what was written since (a patch plus copies of the conflicted files, under
  `<brain state>/rescue/<time>/`), aborts, applies the patch back with `--3way`, and leaves a note in
  `00-Inbox/`. A rebase without the marker was started by a person and is never touched.
- **Session start says it first.** The compass reads, locally and without the network, whether a
  rebase or a merge is in progress and whether commits have gone unpushed for over an hour. When either
  is true, a `## Vault sync: BROKEN on this machine` block goes right under the header. The guardian
  also reports `githooks:rebase-stuck` as a failure after 20 minutes.

## Alternatives considered

- **Keep the rebase on the prompt path with a longer timeout.** Rejected: any deadline can be too
  short for a vault that is far enough ahead, and the cost of cutting it short is a wedged checkout.
- **Union merge for JSON files** (`merge=union`). Rejected: a line union of two JSON documents is
  usually not valid JSON.
- **One writer per state file.** Cleaner where it is possible, and still worth doing; the driver makes
  the two-writer case safe while that is not done.

## Links

- [[2026-09-26-runbook-unwedge-the-vault-sync-after-a-stuck-rebase]]
- [[2026-09-21-failure-vault-sync-unmerged-presence-file-silently-stopped-mac-pulls]]
- [[2026-10-23-decision-skill-notes-use-home-relative-paths]]
- [[2026-09-15-runbook-brain-guardian]]
