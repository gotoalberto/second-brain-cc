# Claude Code integration

The deepest integration: [Claude Code](https://claude.com/claude-code) drives the vault
automatically, with no tool calls to remember. It adds four things a bare MCP server or
CLI can't:

- **Automatic recall** — a `UserPromptSubmit` hook queries the vault on every prompt and
  injects the relevant notes, so context arrives without asking.
- **Session write-back** — a `Stop` hook and the `/save` skill distil what a session
  learned into durable notes before it closes.
- **Agents** — `context-scout`, `planner`, `implementer`, `verifier`, `librarian`,
  `skill-forge`: a pipeline that gathers context, plans, implements in an isolated
  worktree, verifies, and writes back.
- **Slash commands** — `/recall`, `/save`, `/task`, `/ctx`, `/secret`, `/vault-doctor`.

Everything here is a Claude Code convenience layer over the same `_bin/` engine the MCP
server and CLI use. The knowledge, the index, and the write path are identical.

## Install

Run the core bootstrap once, then this integration:

```bash
bash bootstrap.sh                          # core: python check, index, health
bash integrations/claude-code/install.sh   # agents, skills, hooks, sync daemon
```

`install.sh` copies the agents and skills into `~/.claude/`, wires the hooks into
`~/.claude/settings.json` (substituting the vault path), and — on macOS — installs the
git-sync launchd daemon. On Linux/Windows it prints the one-liner to sync from cron.

### Or as a plugin marketplace

The `plugin/` directory is also a Claude Code plugin marketplace, if you prefer that route:

```
/plugin marketplace add /ABSOLUTE/PATH/TO/second-brain-cc/integrations/claude-code/plugin
/plugin install brain@brain-marketplace
```

## Layout

```
plugin/
  .claude-plugin/marketplace.json
  brain/
    .claude-plugin/plugin.json
    agents/          context-scout, planner, implementer, verifier, librarian, skill-forge
    skills/          recall, save, task, ctx, secret, vault-doctor
    hooks/hooks.json SessionStart, UserPromptSubmit, PreToolUse, Stop  (paths use __VAULT__)
```

The hook commands point at `__VAULT__/_bin/*.py`; `install.sh` substitutes `__VAULT__`
with your vault's absolute path. `_bin/` stays at the vault root, shared by all integrations.

## Prefer MCP?

If you'd rather use the portable MCP server with Claude Code instead of this native layer,
see [`../mcp/`](../mcp/). Use one or the other, not both, so a session doesn't write twice.
