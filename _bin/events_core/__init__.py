"""Brain's own event layer: events belong to Brain, agents only carry generated wiring.

  domain.py        the registry (90-Meta/events.json) and the pure rules on it: validation,
                   rendering Claude Code's hooks.json, AGENTS.md and the git hooks, and the
                   file-watch tick (what changed, what to run, what to alert on). No IO.
  ports.py         what the use cases need from the world.
  application.py   the use cases: one watch tick, and the generators.
  adapters.py      the real world: mtimes, a JSON state file, subprocesses, git, files.
  git_pre_commit.py / git_post_commit.py   the git-hook adapters.

Triggers that need no agent at all — the file-watch launchd job (`_bin/brain_watch.py`),
the versioned git hooks (`githooks/`), the MCP server and the `brain` CLI
(`integrations/`) — keep Brain's events firing whichever agent, or none, is writing.
"""
