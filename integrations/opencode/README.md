# OpenCode integration

[OpenCode](https://opencode.ai) is an open-source, terminal-based AI coding agent that is
model-agnostic (Anthropic, OpenAI, Google, local models, 75+ providers). It speaks MCP, so
it plugs into the Second Brain the same way any MCP client does — plus a couple of
OpenCode-specific conveniences.

## 1. Connect the vault over MCP (recommended)

The [MCP server](../mcp/) is the bridge. Register it as a **local** MCP server in your
`opencode.json` — either project-scoped (in the repo root) or global
(`~/.config/opencode/opencode.json`):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "second-brain": {
      "type": "local",
      "command": ["python3", "/ABSOLUTE/PATH/TO/second-brain-cc/integrations/mcp/server.py"],
      "enabled": true,
      "environment": {
        "BRAIN_VAULT": "/ABSOLUTE/PATH/TO/second-brain-cc"
      }
    }
  }
}
```

OpenCode now exposes the vault tools — `recall`, `write_note`, `get_note`, `sync`, … — to
whatever model you run it with. You can also add it interactively with `opencode mcp add`
and check it with `opencode mcp` / `mcp debug`.

Replace `/ABSOLUTE/PATH/TO/second-brain-cc` with your clone's path. (Config schema:
https://opencode.ai/docs/config/ · MCP: https://opencode.ai/docs/mcp-servers/)

## 2. Shell access (alternative / complementary)

OpenCode can run shell commands, so it can also use the [`brain` CLI](../cli/) directly:

```
recall knowledge with:  brain recall "<terms>"
save a durable note with: brain new <path> --title "<title>" --type <type>   (body on stdin)
```

Drop the working rules into an **`AGENTS.md`** at your project root (OpenCode reads it as
project context) — point it at [`../../90-Meta/PROTOCOL-COMPACT.md`](../../90-Meta/PROTOCOL-COMPACT.md),
which is written for exactly this.

## 3. Custom commands (optional)

Mirror the Claude Code slash commands as OpenCode
[custom commands](https://opencode.ai/docs/commands/). For example, a `recall` command whose
body is `Run: brain recall "$ARGUMENTS" and use the results as context.` gives you
`/recall <terms>` in the OpenCode TUI. Do the same for `save`, `sync`, etc.

## 4. Scheduled tasks with OpenCode

The [scheduler](../scheduler/) can drive periodic tasks through OpenCode headlessly. Point
the agent command at the bundled runner:

```bash
export BRAIN_AGENT_CMD=/ABSOLUTE/PATH/TO/second-brain-cc/integrations/scheduler/agent-runners/opencode.sh
export OPENCODE_MODEL=anthropic/claude-sonnet-5     # or any provider/model OpenCode supports
```

`opencode.sh` runs each task's prompt with `opencode run` in non-interactive mode. With the
MCP server registered (step 1), those unattended runs can read and write the vault too.

## Which of MCP vs shell?

Use **MCP** (step 1) for clean, typed tool access to the vault. Use the **CLI** (step 2) if
you prefer OpenCode to just run shell. They're not mutually exclusive — many people register
the MCP server *and* keep the CLI around for scripts and the scheduler.

See also: [`../mcp/`](../mcp/) · [`../cli/`](../cli/) · [`../scheduler/`](../scheduler/) ·
[`../../90-Meta/PORTABILITY.md`](../../90-Meta/PORTABILITY.md).
