---
id: 2026-08-26-convention-code-development-pipeline
title: Code development pipeline and its gates
type: convention
area: [engineering, process]
projects: []
tags: [process, tdd, hexagonal, worktree, verification, dev, task, convention]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-15
supersedes: []
---

## The pipeline

Any task that touches code, spans several files or decides something runs the same steps, in
order. The `task` skill orchestrates them; the `dev` skill adds the code gates on top when
the task produces code.

1. **Context first.** `context-scout` writes a Context Pack from the vault, the repository and
   git history before anyone plans or writes. Whoever executes reads the pack, not the vault.
2. **A worktree per deliverable.** Writing happens in a git worktree with its own branch, never
   in the main checkout. One worktree per unit of merge, not per session or per agent.
   [[2026-08-21-convention-worktree-isolation-per-deliverable]]
3. **A plan.** For more than one file, `planner` writes the plan: approach, files to touch,
   verifiable steps, how it is verified and what is not touched.
4. **Tests first, seen red.** See Gate 1.
5. **Hexagonal architecture.** See Gate 2.
6. **Verify in the real system.** `verifier` runs the tests and checks the effect. A change is
   done when it works where it will be used: the deployed URL, the installed job, the real CLI.
   [[2026-08-30-convention-check-the-effect-not-the-exit-code]]
7. **Save what was learned.** `librarian` writes decisions, conventions and traps to the vault
   before the session closes.

For research, writing or reorganizing the vault, steps 4 and 5 do not apply. Forcing them there
is ceremony.

## Gate 1: tests first

Red, green, refactor, per unit of behaviour. The suite covers the happy path, the edges and the
failure modes before implementation starts: a case that is not in the tests has not been agreed.

What makes this more than intent is how it is checked. The worktree's history must show the test
commit before the implementation commit:

```sh
git -C <worktree> log --oneline --name-only
```

Tests in the same commit as the code, or after it, mean the gate was not passed. Say so; do not
reorder commits to hide it.

If a test passed before the fix, the test is worthless. Asserting that a string appears in the
source proves nothing.

## Gate 2: hexagonal architecture

```
domain/        business rules, no framework, database, HTTP, clock or filesystem
application/   use cases, depending on ports only
ports/         interfaces the inside needs from the outside
adapters/      whatever touches the world, depending inwards
```

The payoff is that the domain and the use cases are tested without standing anything up. If
testing a business rule needs a database or a browser, the boundary is in the wrong place.

## Gate 3: design, only when there is an interface

- **Interview before building.** Ask for references, anti-references and why each one works or
  does not. A visual deliverable built on assumptions gets thrown away, not corrected.
- **Build with design skills, not by hand.** The `dev` skill names a stack of third-party design
  and animation skills; they are installed separately.
- **Critique rounds with fixes applied**, at least three, one of them only about the images:
  framing, crop, quality, consistency, background, and what is actually visible in each.
- **Look at it rendered** after every correction, at several sizes, with the console open.

Backend work skips this gate and no design questions are asked.

## What is left open

Stack decisions (typing, error shapes, state management, test framework) are not fixed here.
They are agreed the first time a project needs them and saved as that project's convention.

## Links

- [[2026-08-21-convention-worktree-isolation-per-deliverable]]
- [[2026-08-30-convention-check-the-effect-not-the-exit-code]]
- [[2026-09-02-convention-deploy-to-prod-on-every-change]]
- [[2026-09-04-convention-removal-tests-run-red-to-green-with-over-deletion-guard]]
- [[2026-09-05-convention-source-pattern-tests-dont-catch-compile-breaks]]
