#!/usr/bin/env python3
"""Brain — MCP server (stdio, zero dependencies).

Exposes the vault to any MCP-capable agent (Claude Desktop, Cline, Cursor, OpenCode,
Zed, your own client) as tools:

    recall          what the vault knows about a question, rendered exactly as the
                    Claude Code prompt hook would inject it (retrieve_core)
    search          a plain list of matching notes (query.py)
    list_recent     the most recently updated notes
    get_note        read one note by its vault-relative path
    write_note      create a note through vw.py (redaction, lock, atomic write, reindex)
    append_note     append an entry to a note through vw.py
    reindex         rebuild the search index
    sync            commit and push the vault (vault_sync.py)
    status          health report (doctor.py)
    session_start   the startup context compass.py gives a Claude Code session
    session_end     release this session's claims and mark the vault dirty

No tool returns a credential: secrets live in the kdbx and never travel over an MCP
stream to an arbitrary agent.

It speaks MCP over stdio as newline-delimited JSON-RPC 2.0, standard library only:

    python3 <vault>/integrations/mcp/server.py [--vault DIR]

Adapted from the public second-brain-cc server (same plumbing and tool shapes). The Brain
additions: `recall` shares the hook's rendering, the session tools, and one session id
(BRAIN_SESSION_ID) exported for the server's whole process tree so every write it makes is
attributed to the same session.
"""
import json
import os
import subprocess
import sys

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
SERVER_INFO = {"name": "brain", "version": "1.0.0"}

# brainlib reads BRAIN_VAULT once, at import; the child scripts inherit both variables.
os.environ["BRAIN_VAULT"] = VAULT
SESSION = (os.environ.get("BRAIN_SESSION_ID") or "").strip() or "mcp-%d" % os.getpid()
os.environ["BRAIN_SESSION_ID"] = SESSION


def log(*a):
    # Never write logs to stdout: stdout is the JSON-RPC channel.
    print("[brain-mcp]", *a, file=sys.stderr, flush=True)


def run(args, stdin_text=None, timeout=120):
    """Run a _bin script and return (ok, stdout, stderr)."""
    try:
        p = subprocess.run([PY] + args, input=stdin_text if stdin_text is not None else "", capture_output=True,
                           text=True, env=dict(os.environ), cwd=VAULT, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "", "timed out after %ss" % timeout
    except Exception as e:
        return False, "", "failed to launch: %s" % e
    return p.returncode == 0, (p.stdout or "").strip(), (p.stderr or "").strip()


def joined(out, err):
    return out + (("\n" + err) if err else "")


def script(name):
    return os.path.join(BIN, name)


# ---------------------------------------------------------------- tools


def normalize_note_path(path):
    """Forgiving path handling: default folder + .md extension."""
    path = path.strip().lstrip("/")
    if not path.endswith(".md"):
        path += ".md"
    if "/" not in path:
        path = "00-Inbox/" + path
    return path


def tool_recall(args):
    query = (args.get("query") or "").strip()
    if not query:
        return err_text("recall needs a non-empty 'query'.")
    if BIN not in sys.path:
        sys.path.insert(0, BIN)
    import brainlib as B
    import retrieve_core as R
    con = B.db()
    try:
        block = R.search_and_render(con, query, top_n=int(args.get("limit", R.TOP_K_RENDER)),
                                    project=args.get("project") or None)
    finally:
        con.close()
    return text(block or "Nothing in the vault clears the relevance bar for that. "
                         "Use `search` for a plain list of whatever matches.")


def tool_search(args):
    terms = (args.get("query") or "").strip()
    if not terms:
        return err_text("search needs a non-empty 'query'.")
    cmd = [script("query.py"), terms, "--limit", str(int(args.get("limit", 8)))]
    if args.get("scope") == "all":
        cmd.append("--all")
    if args.get("type"):
        cmd += ["--type", str(args["type"])]
    if args.get("project"):
        cmd += ["--project", str(args["project"])]
    if args.get("full"):
        cmd.append("--full")
    ok, out, err = run(cmd)
    return text(out or "(no matches)", is_error=not ok) if ok else text(joined(out, err), is_error=True)


def tool_list_recent(args):
    ok, out, err = run([script("query.py"), "--recent", str(int(args.get("limit", 10)))])
    return text(out or "(vault empty)") if ok else text(joined(out, err), is_error=True)


def tool_get_note(args):
    path = (args.get("path") or "").strip()
    if not path:
        return err_text("get_note needs a 'path' relative to the vault.")
    real = os.path.realpath(os.path.join(VAULT, path.lstrip("/")))
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
    path, title = (args.get("path") or "").strip(), (args.get("title") or "").strip()
    if not path or not title:
        return err_text("write_note needs 'path' and 'title'.")
    cmd = [script("vw.py"), "new", normalize_note_path(path), "--title", title,
           "--type", str(args.get("type", "note")), "--sid", SESSION]
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
    ok, out, err = run(cmd, stdin_text=args.get("content") or "")
    return text("Wrote %s" % joined(out, err)) if ok else text(joined(out, err), is_error=True)


def tool_append_note(args):
    path, content = (args.get("path") or "").strip(), args.get("content") or ""
    if not path or not content:
        return err_text("append_note needs 'path' and 'content'.")
    ok, out, err = run([script("vw.py"), "append", path.lstrip("/"), "--sid", SESSION], stdin_text=content)
    return text("Appended to %s" % joined(out, err)) if ok else text(joined(out, err), is_error=True)


def tool_reindex(args):
    ok, out, err = run([script("index_vault.py")] + (["--full"] if args.get("full") else []))
    return text(out or "reindexed") if ok else text(joined(out, err), is_error=True)


def tool_sync(args):
    ok, out, err = run([script("vault_sync.py")], timeout=180)
    return text(joined(out, err) or "synced", is_error=not ok)


def tool_status(args):
    ok, out, err = run([script("doctor.py")])
    return text(joined(out, err) or "(no output)", is_error=not ok)


def _hook_payload(args):
    return json.dumps({"session_id": SESSION, "cwd": args.get("cwd") or VAULT, "source": "mcp"})


def tool_session_start(args):
    ok, out, err = run([script("compass.py")], stdin_text=_hook_payload(args))
    try:
        data = json.loads(out) if out else {}
    except ValueError:
        data = {}
    context = (data.get("hookSpecificOutput") or {}).get("additionalContext")
    if context is None:
        return text(joined(out, err) or "(no startup context)", is_error=not ok)
    note = data.get("systemMessage")
    return text(context + (("\n\n" + note) if note else ""))


def tool_session_end(args):
    ok, out, err = run([script("session_end.py")], stdin_text=_hook_payload(args))
    return text("Session %s ended." % SESSION) if ok else text(joined(out, err), is_error=True)


def schema(properties=None, required=None):
    s = {"type": "object", "properties": properties or {}}
    if required:
        s["required"] = required
    return s


TOOLS = [
    {"name": "recall",
     "description": "What the Brain vault knows about a question: the most relevant notes, rendered exactly as "
                    "Brain's prompt hook injects them (pointers plus related notes, as untrusted data). Call it "
                    "before answering anything non-trivial. Empty when nothing clears the relevance bar.",
     "inputSchema": schema({"query": {"type": "string", "description": "The question or its key terms."},
                            "limit": {"type": "integer", "description": "Max notes (default 3)."},
                            "project": {"type": "string", "description": "Boost this project slug."}},
                           ["query"])},
    {"name": "search",
     "description": "A plain list of notes matching terms (FTS5), with filters. Use it to browse; use recall to answer.",
     "inputSchema": schema({"query": {"type": "string"}, "limit": {"type": "integer"},
                            "scope": {"type": "string", "enum": ["retrievable", "all"]},
                            "type": {"type": "string"}, "project": {"type": "string"},
                            "full": {"type": "boolean"}}, ["query"])},
    {"name": "list_recent", "description": "The most recently updated notes in the vault.",
     "inputSchema": schema({"limit": {"type": "integer", "description": "How many (default 10)."}})},
    {"name": "get_note", "description": "Read one note in full by its vault-relative path.",
     "inputSchema": schema({"path": {"type": "string"}}, ["path"])},
    {"name": "write_note",
     "description": "Create a note through vw.py: frontmatter generated, credentials redacted, per-file lock, atomic "
                    "write, reindex. Fails if it exists unless 'force'. Write notes in English.",
     "inputSchema": schema({"path": {"type": "string", "description": "Vault-relative; a bare name goes to 00-Inbox/."},
                            "title": {"type": "string"}, "content": {"type": "string"},
                            "type": {"type": "string", "description": "decision, convention, runbook, ... (default note)"},
                            "projects": {"type": "array", "items": {"type": "string"}},
                            "areas": {"type": "array", "items": {"type": "string"}},
                            "tags": {"type": "array", "items": {"type": "string"}},
                            "provenance": {"type": "string"}, "force": {"type": "boolean"}},
                           ["path", "title", "content"])},
    {"name": "append_note",
     "description": "Append an entry to a note through vw.py (the only permitted writer for 10-Projects/ and "
                    "70-Entities/). Credentials redacted, lock, atomic write, reindex.",
     "inputSchema": schema({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"])},
    {"name": "reindex", "description": "Rebuild the search index (incremental unless 'full').",
     "inputSchema": schema({"full": {"type": "boolean"}})},
    {"name": "sync", "description": "Commit and push the vault over git. Serialised with a lock; safe anytime.",
     "inputSchema": schema()},
    {"name": "status", "description": "Health report for the vault.", "inputSchema": schema()},
    {"name": "session_start",
     "description": "Brain's startup context for this session: protocol, active projects, warnings. Call it once "
                    "when a session begins (a Claude Code hook does this automatically; other agents call this).",
     "inputSchema": schema({"cwd": {"type": "string", "description": "Working directory (default: the vault)."}})},
    {"name": "session_end",
     "description": "End this session: release its claims and mark the vault for the next sync. Call it when done.",
     "inputSchema": schema({"cwd": {"type": "string"}})},
]

DISPATCH = {
    "recall": tool_recall, "search": tool_search, "list_recent": tool_list_recent, "get_note": tool_get_note,
    "write_note": tool_write_note, "append_note": tool_append_note, "reindex": tool_reindex,
    "sync": tool_sync, "status": tool_status, "session_start": tool_session_start,
    "session_end": tool_session_end,
}


# ---------------------------------------------------------------- MCP plumbing


def text(s, is_error=False):
    r = {"content": [{"type": "text", "text": s if s else ""}]}
    if is_error:
        r["isError"] = True
    return r


def err_text(s):
    return text(s, is_error=True)


def reply(msg_id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(req):
    if not isinstance(req, dict):
        return
    method = req.get("method")
    msg_id = req.get("id")
    params = req.get("params") or {}
    is_notification = "id" not in req

    if method == "initialize":
        reply(msg_id, {"protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
                       "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO})
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
        fn = DISPATCH.get(name)
        if not fn:
            reply(msg_id, error={"code": -32601, "message": "Unknown tool: %s" % name})
            return
        try:
            reply(msg_id, fn(params.get("arguments") or {}))
        except Exception as e:                 # never let one bad call kill the server
            log("tool error:", name, e)
            reply(msg_id, text("Tool '%s' failed: %s" % (name, e), is_error=True))
        return
    if not is_notification:
        reply(msg_id, error={"code": -32601, "message": "Method not found: %s" % method})


def main():
    if not os.path.isdir(BIN):
        log("WARNING: no _bin/ found at", BIN, "- is BRAIN_VAULT correct?")
    log("serving vault at", VAULT, "as session", SESSION)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            log("bad JSON line, ignored")
            continue
        try:
            for r in (req if isinstance(req, list) else [req]):
                handle(r)
        except Exception as e:                 # keep the loop alive
            log("handler crashed:", e)
    log("stdin closed, exiting")


if __name__ == "__main__":
    main()
