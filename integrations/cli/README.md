# CLI integration

`brain` is a tiny command-line wrapper over the vault, for **any agent that can run a
shell command** (and for you at a terminal). No MCP, no plugin — just a command.

Use it when your assistant can execute shell but doesn't speak MCP, or when you want to
drive the vault from scripts, cron, a Makefile, or your own tooling.

## Install

Put it on your `PATH`:

```bash
ln -s "$PWD/integrations/cli/brain" /usr/local/bin/brain    # or ~/.local/bin/brain
```

The vault is auto-detected as this repository. If you keep the vault elsewhere, export
`BRAIN_VAULT=/path/to/vault`.

## Commands

```bash
brain recall <terms...> [--all] [--limit N] [--type T] [--project P] [--full]
brain recent [N]
brain get   <vault/relative/path.md>
brain new   <path> --title "T" [--type note] [--tag t] [--project p] [--area a]   # body on stdin
brain append <path>                                                              # text on stdin
brain index [--full]
brain sync
brain status
brain secret <get|put|ref|check> ...     # 1Password-backed credentials (optional)
brain mcp                                 # run the MCP server on stdio
```

## Examples

```bash
brain recall "vector database decision"
brain recent 5
echo "Decided to use Postgres over Mongo because of the relational access pattern." \
  | brain new 30-Knowledge/2026-01-20-decision-postgres.md --title "Postgres over Mongo" --type decision --tag database
brain get 30-Knowledge/2026-01-20-decision-postgres.md
brain sync
```

## Point an agent at it

Any agent framework that can shell out can use the vault by calling `brain`. Tell your
agent, in its system prompt or tool description:

> To recall knowledge, run `brain recall "<terms>"`. To save a durable note, pipe the
> body into `brain new <path> --title "<title>" --type <type>`. Never write secrets into
> notes — store them with `brain secret put ...` and reference them by `op://` path.

That is the whole contract. See [`../../90-Meta/AGENT-PROTOCOL.md`](../../90-Meta/AGENT-PROTOCOL.md)
for the full conventions.
