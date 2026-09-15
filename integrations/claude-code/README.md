# Claude Code integration

The deepest integration: [Claude Code](https://claude.com/claude-code) drives the vault on its own,
with no tool calls to remember. On top of the MCP server and the CLI it adds:

- **Automatic recall**: a `UserPromptSubmit` hook queries the vault on every prompt and injects the
  relevant notes.
- **Session write-back**: a `Stop` hook and the `/save` skill keep a session from closing without
  saving what it decided.
- **Agents**: `context-scout`, `planner`, `implementer`, `verifier`, `librarian`, `skill-forge`, a
  pipeline that gathers context, plans, implements in an isolated worktree, verifies and writes back.
- **Skills**: `/task`, `/ctx`, `/recall`, `/save`, `/vault-doctor`, `/kp` (KeePass credentials),
  `/dev` (the development pipeline) and `/job-search`.

Everything here is a convenience layer over the same `_bin/` engine the MCP server and the CLI use.
The knowledge, the index and the write path are identical.

## Install

```bash
bash bootstrap.sh                          # core: python check, index, health
bash integrations/claude-code/install.sh   # skills, agents, hooks, recommended settings
bash integrations/first-run/setup.sh       # optional pieces, one yes at a time
```

`install.sh`:

1. installs the skills and agents into `~/.claude` with `_bin/install_plugin.py install`. The vault's
   copy is canonical; `__VAULT__` in a skill or agent becomes your vault's path in the installed copy,
   and a live edit is back-ported with the path turned back into `__VAULT__`;
2. merges the hooks into `~/.claude/settings.json` with `_bin/guardian.py repair --hooks-only`, which
   backs the file up and never removes anything it did not install;
3. shows the recommended settings in `settings.example.json` (permissions and defaults) and merges
   them only after your yes, with `_bin/claude_settings.py merge`: it adds entries you do not have,
   never changes a value you set, and keeps a backup.

It installs no scheduled job. The first run asks whether to install the guardian, the sync, the task
runner and the file watch with launchd, systemd user units or cron; once accepted, the guardian keeps
the hooks, the skills and those jobs in step every 15 minutes.

### Or as a plugin marketplace

The `plugin/` directory is also a Claude Code plugin marketplace:

```
/plugin marketplace add /path/to/second-brain-cc/integrations/claude-code/plugin
/plugin install brain@brain-marketplace
```

The hooks in `plugin/brain/hooks/hooks.json` are generated from `90-Meta/events.json` and name an
origin vault (`/home/brain-origin/Brain`) that the installers rewrite; install through `install.sh`
so they point at your vault.

## Layout

```
plugin/
  .claude-plugin/marketplace.json
  brain/
    .claude-plugin/plugin.json
    agents/          context-scout, planner, implementer, verifier, librarian, skill-forge
    skills/          task, ctx, recall, save, vault-doctor, kp, dev, job-search
    hooks/hooks.json generated from 90-Meta/events.json (brain_watch.py generate)
settings.example.json   recommended settings, merged with claude_settings.py
install.sh
```

## Changing an agent's model or effort

Each agent is a Markdown file under `plugin/brain/agents/` whose frontmatter names its `model`,
`effort` and `tools`. Edit it there and run `python3 _bin/install_plugin.py sync` (the guardian does
it every 15 minutes when it is installed).

## Prefer MCP?

To use the portable MCP server with Claude Code instead of this layer, see [`../mcp/`](../mcp/). Use
one or the other, not both, so a session does not write twice.
