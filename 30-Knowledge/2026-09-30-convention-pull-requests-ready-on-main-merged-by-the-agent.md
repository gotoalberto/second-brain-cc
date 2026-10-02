---
id: 2026-09-30-convention-pull-requests-ready-on-main-merged-by-the-agent
title: Pull requests opened ready on main and merged by the agent
type: convention
area: [git, devex]
projects: []
tags: [git, github, pull-requests, merge, deploy, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-02
supersedes: []
---

# Pull requests opened ready on main and merged by the agent

## Scope

This is the harness default for repositories that do use pull requests: shared repositories, and
the user's own repositories wired to deploy from `main`. Repositories the agent alone maintains merge
straight to `main` with no pull request
([[2026-09-17-convention-solo-repos-merge-to-main-no-pr]]). A team's own flow (required reviewers,
its target branch) always wins over this note.

A user who prefers to approve each merge switches the default by saying so once; the agent then asks
before every merge, naming the pull request, what it changes, the CI state and whether merging
deploys. Record that preference in memory so later sessions keep it.

## The rule

- **Open it ready, never as a draft.** A draft greys out every merge button, and a user who tries to
  merge it is stuck until someone flips it.
- **Base it on `main`, never on another pull request's branch.** A stacked pull request merges into
  its base branch. When the user merged one, the change landed in the other feature branch, nothing
  reached production, and the user believed it had. When work depends on an unmerged pull request,
  fold it into the same one or wait.
- **Merge commit, never squash or rebase** (`gh pr merge <n> --merge`). Squashing erases the
  test-first history (failing test, then implementation) that a reviewer reads commit by commit.
- **The agent merges once the work is verified**, as the last step of the task, without stopping at
  an open pull request. Read the CI result first and do not chain the merge blindly after a watch: a
  red check must be shown to fail on `main` too before merging over it, otherwise fix it. Never
  `--admin` to bypass branch protection unless the user asks; when protection refuses the merge,
  report which setting blocks it.
- **Finishing means deployed.** After the merge, check that the production deployment of the merged
  commit succeeded and that the live site shows the change
  ([[2026-09-02-convention-deploy-to-prod-on-every-change]]). The reply says plainly that it is live
  and where.
- **No closing offers.** A reply that ends with "I can also do the same on the other page if you
  want" is a question in disguise. Do the change that was asked, merge, deploy, report.

## Permissions

The merge runs without a prompt only when `Bash(gh pr merge:*)` is in the `allow` list of the
settings on that machine. The agent cannot add it itself; the person adds it
([[2026-09-30-howto-grant-claude-code-allow-rules-from-another-machine]]).

## Links

- [[2026-09-17-convention-solo-repos-merge-to-main-no-pr]]
- [[2026-09-02-convention-deploy-to-prod-on-every-change]]
- [[2026-08-26-convention-code-development-pipeline]]
