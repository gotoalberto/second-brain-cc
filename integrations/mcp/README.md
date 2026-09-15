# MCP integration

A zero-dependency [Model Context Protocol](https://modelcontextprotocol.io) server that
exposes Brain to **any MCP-capable agent**: Claude Desktop, Cline, Cursor, Continue, Zed,
OpenCode, Windsurf or your own client. Standard library only, stdio transport.

## Tools

| Tool | What it does |
|---|---|
| `recall` | What the vault knows about a question, rendered exactly as Brain's Claude Code prompt hook injects it (`_bin/retrieve_core.py`). Empty when nothing is relevant. |
| `search` | A plain list of matching notes, with filters (`_bin/query.py`). |
| `list_recent` | The most recently updated notes. |
| `get_note` | Read one note by its vault-relative path (paths outside the vault are refused). |
| `write_note` | Create a note through `vw.py`: redaction, lock, atomic write, reindex. |
| `append_note` | Append to a note through `vw.py`, the only permitted writer for `10-Projects/` and `70-Entities/`. |
| `reindex` | Rebuild the search index. |
| `sync` | Commit and push the vault (`vault_sync.py`). |
| `status` | Health report (`doctor.py`). |
| `session_start` | The startup context `compass.py` gives a Claude Code session. Call it once at the start. |
| `session_end` | Release this session's claims and mark the vault for the next sync. Call it at the end. |

**There is no credential tool.** Secrets live in the kdbx and are not handed to an agent
over an MCP stream; notes keep only `kp://` references.

The server exports one `BRAIN_SESSION_ID` (`mcp-<pid>` unless the client already set one)
for its whole process tree, so every write it makes is attributed to the same session.

## Register it

Replace `/path/to/Brain` with the vault's absolute path.

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{"mcpServers": {"brain": {"command": "python3", "args": ["/path/to/Brain/integrations/mcp/server.py"]}}}
```

**Cline, Cursor, Continue, Windsurf, Roo** (their MCP settings JSON):

```json
{"mcpServers": {"brain": {"command": "python3",
  "args": ["/path/to/Brain/integrations/mcp/server.py"],
  "env": {"BRAIN_VAULT": "/path/to/Brain"}}}}
```

**OpenCode** (`opencode.json`):

```json
{"$schema": "https://opencode.ai/config.json",
 "mcp": {"brain": {"type": "local", "command": ["python3", "/path/to/Brain/integrations/mcp/server.py"],
                   "enabled": true, "environment": {"BRAIN_VAULT": "/path/to/Brain"}}}}
```

**Zed** (`settings.json`):

```json
{"context_servers": {"brain": {"command": {"path": "python3",
  "args": ["/path/to/Brain/integrations/mcp/server.py"]}}}}
```

**Claude Code CLI**, if you want the server instead of the hooks (not both: the hooks already
do what these tools do, and doing it twice double-counts):

```bash
claude mcp add brain -- python3 /path/to/Brain/integrations/mcp/server.py
```

Registration is per agent and per machine, by hand: there is no universal mechanism.

## Test it by hand

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"recall","arguments":{"query":"guardian"}}}' \
  | python3 integrations/mcp/server.py
```

You should see the `initialize` result, the tool list, and the notes about the guardian. Logs
go to stderr, never to stdout (stdout is the protocol channel). The automated version of this
handshake is `_bin/mcp_server_test.py`.
