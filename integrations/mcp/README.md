# MCP integration

A zero-dependency [Model Context Protocol](https://modelcontextprotocol.io) server
that exposes your vault to **any MCP-capable agent** — Claude Desktop, Cline, Cursor,
Continue, Zed, Windsurf, or your own client. This is the universal way to plug the
Second Brain into an assistant: if it speaks MCP, it can use the vault.

The server is `server.py`. It uses the Python standard library only (no `pip install`,
no SDK) and speaks MCP over stdio.

## Tools it exposes

| Tool | What it does |
|---|---|
| `recall` | Full-text search over the vault (FTS5). The main entry point. |
| `list_recent` | The most recently updated notes. |
| `get_note` | Read one note in full by its vault-relative path. |
| `write_note` | Create a new note. Credentials are auto-redacted; write is atomic + reindexed. |
| `append_note` | Append a timestamped entry to a note's log. |
| `reindex` | Rebuild the search index (incremental unless `full`). |
| `sync` | Commit & push the vault over git. |
| `status` | Health report for the vault. |

Every write goes through the same `_bin/` path the CLI and hooks use, so redaction,
per-file locking and reindexing happen no matter which agent is driving.

## Configure your client

The server auto-detects the vault as the repository this file lives in. If your vault
is elsewhere, set `BRAIN_VAULT` (or pass `--vault /path/to/vault`).

Replace `/ABSOLUTE/PATH/TO/second-brain-cc` below with your clone's absolute path.

### Claude Desktop

Edit `claude_desktop_config.json`
(macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`,
Windows: `%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "second-brain": {
      "command": "python3",
      "args": ["/ABSOLUTE/PATH/TO/second-brain-cc/integrations/mcp/server.py"]
    }
  }
}
```

### Cline / Cursor / Continue / Windsurf / Roo

These read the same `mcpServers` shape (in the extension's MCP settings JSON):

```json
{
  "mcpServers": {
    "second-brain": {
      "command": "python3",
      "args": ["/ABSOLUTE/PATH/TO/second-brain-cc/integrations/mcp/server.py"],
      "env": { "BRAIN_VAULT": "/ABSOLUTE/PATH/TO/second-brain-cc" }
    }
  }
}
```

### Claude Code (CLI)

If you use Claude Code and want the MCP server *instead of* the native plugin:

```bash
claude mcp add second-brain -- python3 /ABSOLUTE/PATH/TO/second-brain-cc/integrations/mcp/server.py
```

(The richer Claude Code integration — hooks, agents, slash commands — lives in
[`../claude-code/`](../claude-code/). Use one or the other, not both, to avoid double writes.)

### Zed

In `settings.json` under `context_servers`:

```json
{
  "context_servers": {
    "second-brain": {
      "command": { "path": "python3",
        "args": ["/ABSOLUTE/PATH/TO/second-brain-cc/integrations/mcp/server.py"] }
    }
  }
}
```

### Any other MCP client

Run this command and speak MCP over its stdio:

```bash
python3 /ABSOLUTE/PATH/TO/second-brain-cc/integrations/mcp/server.py
```

## Test it by hand

You can drive the server with plain JSON-RPC lines:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"recall","arguments":{"query":"onboarding"}}}' \
  | python3 integrations/mcp/server.py
```

You should see the `initialize` result, the tool list, and search results.

## Notes

- **Requirements:** Python 3.8+ with SQLite/FTS5 (bundled with CPython on macOS, Linux
  and Windows). Nothing else.
- **Logs** go to stderr (stdout is the protocol channel), so they never corrupt the stream.
- The server is a thin wrapper: it shells out to `_bin/query.py`, `vw.py`,
  `index_vault.py`, `vault_sync.py` and `doctor.py`. Read [`server.py`](server.py) — it's
  short.
