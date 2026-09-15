# CLI integration

`brain` is a small command-line wrapper over the vault, for **any agent that can run a shell
command** and for you at a terminal. No MCP, no plugin, no agent account: a command.

## Install

```bash
chmod +x ~/Brain/integrations/cli/brain
ln -s ~/Brain/integrations/cli/brain ~/.local/bin/brain     # or /usr/local/bin/brain
```

The vault is the repository the script lives in; export `BRAIN_VAULT=/path/to/vault` to point
it elsewhere.

## Commands

```bash
brain recall <terms...>          # what the vault knows, rendered exactly as the prompt hook injects it
brain search <terms...> [--all] [--limit N] [--type T] [--project P] [--full]
brain recent [N]
brain get    <vault/relative/path.md>
brain new    <path> --title "T" [--type note] [--tag t] [--project p] [--area a]   # body on stdin
brain append <path>                                                              # text on stdin
brain index [--full]
brain sync
brain status
brain session-start              # startup context: protocol, active projects, warnings
brain session-end                # release this session's claims, mark the vault dirty
brain hook <event-id> [--payload JSON]
                                 # run any event's hook handler with the stdin JSON a Claude Code hook
                                 # gets; exit code is the handler's. See 90-Meta/HOOKS-WITHOUT-CLAUDE.md
brain mcp                        # run the MCP server on stdio
```

## Sessions

Every invocation runs under one session id: `BRAIN_SESSION_ID` if the caller exported it, else
`cli-<pid>`. Notes written with `brain new` / `brain append` are credited to that session. An
agent that wants a whole working session attributed as one should export `BRAIN_SESSION_ID`
once, run `brain session-start`, work, and finish with `brain session-end`.

## Point an agent at it

In the agent's system prompt or tool description:

> Before answering anything non-trivial, run `brain recall "<terms from the question>"`. To
> save a durable note, pipe the body into `brain new <path> --title "<title>" --type <type>`;
> to add to a project or entity note, use `brain append <path>`. Write notes in English. Never
> put credentials in a note: they live in the kdbx and a note keeps a `kp://` reference.

Without an agent adapter nothing fires on its own for that agent: see the degraded-mode table
in `AGENTS.md` at the vault root for what to call and when.
