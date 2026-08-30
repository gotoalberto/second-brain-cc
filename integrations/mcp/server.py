#!/usr/bin/env python3
"""Second Brain — MCP server (stdio, zero dependencies).

Exposes the vault to any MCP-capable agent (Claude Desktop, Cline, Cursor,
Continue, Zed, your own client…) as a small set of tools:

    recall        search the vault (FTS5, not grep)
    list_recent   the most recently updated notes
    get_note      read one note by its path
    write_note    create a new note (credentials are auto-redacted)
    append_note   append a timestamped entry to a note
    reindex       rebuild the search index
    sync          commit & push the vault over git
    status        health report

It speaks MCP over stdio using newline-delimited JSON-RPC 2.0 and the Python
standard library only — no `pip install`, no SDK. Point your agent at:

    python3 <vault>/integrations/mcp/server.py

The vault is auto-detected as the repo this file lives in; override with the
BRAIN_VAULT environment variable or --vault.

This is a thin, safe wrapper over the same `_bin/` tools the CLI and the hooks
use, so every write goes through the vault's redaction + locking + reindex path.
"""
import os
import sys
import json
import subprocess

# ---------------------------------------------------------------------------
# Locate the vault. This file lives at <vault>/integrations/mcp/server.py, so
# the vault is three directories up. BRAIN_VAULT (or --vault) wins if set.
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_VAULT = os.path.dirname(os.path.dirname(HERE))


def resolve_vault(argv):
    for i, a in enumerate(argv):
        if a == "--vault" and i + 1 < len(argv):
            return os.path.abspath(os.path.expanduser(argv[i + 1]))
        if a.startswith("--vault="):
            return os.path.abspath(os.path.expanduser(a.split("=", 1)[1]))
    return os.path.abspath(os.environ.get("BRAIN_VAULT") or DEFAULT_VAULT)


VAULT = resolve_vault(sys.argv[1:])
BIN = os.path.join(VAULT, "_bin")
PY = sys.executable or "/usr/bin/python3"
PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "second-brain", "version": "1.0.0"}


def log(*a):
    # Never write logs to stdout: stdout is the JSON-RPC channel.
    print("[second-brain-mcp]", *a, file=sys.stderr, flush=True)


def run(args, stdin_text=None, timeout=120):
    """Run a _bin script and return (ok, combined_output)."""
    env = dict(os.environ)
    env["BRAIN_VAULT"] = VAULT
    try:
        p = subprocess.run(
            [PY] + args,
            input=stdin_text,
            capture_output=True,
            text=True,
            env=env,
            cwd=VAULT,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "timed out after %ss" % timeout
    except Exception as e:  # pragma: no cover - defensive
        return False, "failed to launch: %s" % e
    out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr.strip() else "")
    return p.returncode == 0, out.strip()


def script(name):
    return os.path.join(BIN, name)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
def normalize_note_path(path):
    """Forgiving path handling: default folder + .md extension."""
    path = path.strip().lstrip("/")
    if not path.endswith(".md"):
        path += ".md"
    if "/" not in path:
        path = "00-Inbox/" + path
    return path


def tool_recall(args):
    terms = args.get("query", "").strip()
    if not terms:
        return err_text("recall needs a non-empty 'query'.")
    cmd = [script("query.py"), terms, "--limit", str(int(args.get("limit", 8)))]
    if args.get("scope") == "all":
        cmd.append("--all")
    if args.get("type"):
        cmd += ["--type", str(args["type"])]
    if args.get("project"):
        cmd += ["--project", str(args["project"])]
    if args.get("full"):
        cmd.append("--full")
    ok, out = run(cmd)
    return text(out or "(no matches)", is_error=not ok)


def tool_list_recent(args):
    limit = int(args.get("limit", 10))
    ok, out = run([script("query.py"), "--recent", str(limit)])
    return text(out or "(vault empty)", is_error=not ok)


def tool_get_note(args):
    path = args.get("path", "").strip()
    if not path:
        return err_text("get_note needs a 'path' relative to the vault.")
    full = os.path.join(VAULT, path.lstrip("/"))
    real = os.path.realpath(full)
    if not real.startswith(os.path.realpath(VAULT) + os.sep):
        return err_text("Path escapes the vault.")
    if not os.path.isfile(real):
        return err_text("No such note: %s" % path)
    try:
        with open(real, encoding="utf-8", errors="replace") as f:
            return text(f.read())
    except Exception as e:
        return err_text("Could not read %s: %s" % (path, e))


def tool_write_note(args):
    path = args.get("path", "").strip()
    title = args.get("title", "").strip()
    content = args.get("content", "")
    if not path or not title:
        return err_text("write_note needs 'path' and 'title'.")
    path = normalize_note_path(path)
    cmd = [script("vw.py"), "new", path, "--title", title,
           "--type", str(args.get("type", "note"))]
    for p in args.get("projects", []) or []:
        cmd += ["--project", str(p)]
    for a in args.get("areas", []) or []:
        cmd += ["--area", str(a)]
    for t in args.get("tags", []) or []:
        cmd += ["--tag", str(t)]
    if args.get("provenance"):
        cmd += ["--provenance", str(args["provenance"])]
    if args.get("force"):
        cmd.append("--force")
    ok, out = run(cmd, stdin_text=content or "")
    if ok:
        return text("Wrote %s" % out)
    return text(out, is_error=True)


def tool_append_note(args):
    path = args.get("path", "").strip()
    content = args.get("content", "")
    if not path or not content:
        return err_text("append_note needs 'path' and 'content'.")
    ok, out = run([script("vw.py"), "append", path.lstrip("/")], stdin_text=content)
    return text(("Appended to %s" % out) if ok else out, is_error=not ok)


def tool_reindex(args):
    ok, out = run([script("index_vault.py")] + (["--full"] if args.get("full") else []))
    return text(out or "reindexed", is_error=not ok)


def tool_sync(args):
    ok, out = run([script("vault_sync.py")], timeout=180)
    return text(out or "synced", is_error=not ok)


def tool_status(args):
    ok, out = run([script("doctor.py")])
    return text(out or "(no output)", is_error=not ok)


TOOLS = [
    {
        "name": "recall",
        "description": "Search the Second Brain vault using its full-text index "
                       "(FTS5). Returns the most relevant notes. Prefer this over "
                       "grep/file search for anything in the knowledge base.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms."},
                "limit": {"type": "integer", "description": "Max results (default 8)."},
                "scope": {"type": "string", "enum": ["retrievable", "all"],
                          "description": "'retrievable' (default) skips sessions, "
                                         "context-packs, inbox and meta; 'all' includes them."},
                "type": {"type": "string", "description": "Filter by note type "
                         "(decision, reference, convention, knowledge, project, ...)."},
                "project": {"type": "string", "description": "Filter by project slug."},
                "full": {"type": "boolean", "description": "Return whole notes, not snippets."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_recent",
        "description": "List the most recently updated notes in the vault.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "How many (default 10)."}},
        },
    },
    {
        "name": "get_note",
        "description": "Read one note in full by its path relative to the vault root "
                       "(e.g. '30-Knowledge/2026-08-30-my-note.md').",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Vault-relative path."}},
            "required": ["path"],
        },
    },
    {
        "name": "write_note",
        "description": "Create a new note in the vault. Frontmatter is generated from the "
                       "arguments; credentials in the body are auto-redacted; the write is "
                       "atomic and the search index is updated. Fails if the note already "
                       "exists unless 'force' is set.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Vault-relative path. A bare name "
                         "goes to 00-Inbox/; '.md' is added if missing."},
                "title": {"type": "string", "description": "Human title."},
                "content": {"type": "string", "description": "Markdown body of the note."},
                "type": {"type": "string", "description": "Note type (default 'note')."},
                "projects": {"type": "array", "items": {"type": "string"}},
                "areas": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "provenance": {"type": "string", "description": "Where this came from."},
                "force": {"type": "boolean", "description": "Overwrite if it exists."},
            },
            "required": ["path", "title", "content"],
        },
    },
    {
        "name": "append_note",
        "description": "Append a timestamped entry to an existing note's log. Credentials "
                       "are auto-redacted; the write is atomic and reindexed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Vault-relative path."},
                "content": {"type": "string", "description": "Text to append."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "reindex",
        "description": "Rebuild the vault's full-text search index. Fast and incremental "
                       "unless 'full' is set.",
        "inputSchema": {
            "type": "object",
            "properties": {"full": {"type": "boolean", "description": "Force a full reindex."}},
        },
    },
    {
        "name": "sync",
        "description": "Commit and push the vault over git (pull --rebase first). "
                       "Serialised with a lock, safe to call anytime.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "status",
        "description": "Print a health report for the vault (note counts, index state, "
                       "graph, pending sync, etc.).",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

DISPATCH = {
    "recall": tool_recall,
    "list_recent": tool_list_recent,
    "get_note": tool_get_note,
    "write_note": tool_write_note,
    "append_note": tool_append_note,
    "reindex": tool_reindex,
    "sync": tool_sync,
    "status": tool_status,
}


# ---------------------------------------------------------------------------
# MCP content helpers
# ---------------------------------------------------------------------------
def text(s, is_error=False):
    r = {"content": [{"type": "text", "text": s if s else ""}]}
    if is_error:
        r["isError"] = True
    return r


def err_text(s):
    return text(s, is_error=True)


# ---------------------------------------------------------------------------
# JSON-RPC plumbing (newline-delimited over stdio)
# ---------------------------------------------------------------------------
def reply(msg_id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(req):
    method = req.get("method")
    msg_id = req.get("id")
    params = req.get("params") or {}
    is_notification = "id" not in req

    if method == "initialize":
        client_ver = params.get("protocolVersion")
        reply(msg_id, {
            "protocolVersion": client_ver or PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
        return
    if method in ("notifications/initialized", "initialized", "notifications/cancelled"):
        return
    if method == "ping":
        reply(msg_id, {})
        return
    if method == "tools/list":
        reply(msg_id, {"tools": TOOLS})
        return
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = DISPATCH.get(name)
        if not fn:
            reply(msg_id, error={"code": -32601, "message": "Unknown tool: %s" % name})
            return
        try:
            reply(msg_id, fn(args))
        except Exception as e:  # never let one bad call kill the server
            log("tool error:", name, e)
            reply(msg_id, text("Tool '%s' failed: %s" % (name, e), is_error=True))
        return

    # Unknown method
    if not is_notification:
        reply(msg_id, error={"code": -32601, "message": "Method not found: %s" % method})


def main():
    if not os.path.isdir(BIN):
        log("WARNING: no _bin/ found at", BIN, "- is BRAIN_VAULT correct?")
    log("serving vault at", VAULT)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            log("bad JSON line, ignored")
            continue
        try:
            if isinstance(req, list):          # JSON-RPC batch
                for r in req:
                    handle(r)
            else:
                handle(req)
        except Exception as e:                 # keep the loop alive
            log("handler crashed:", e)
    log("stdin closed, exiting")


if __name__ == "__main__":
    main()
