#!/usr/bin/env python3
"""Smoke test for integrations/mcp/server.py — Brain over MCP, for any agent.

Drives the server through the scripted `initialize → tools/list → tools/call` handshake
against a temporary vault: a copy of _bin with the scripts that would reach the network
or the real vault (compass, session_end, vault_sync, doctor, presence, lease) replaced
by stubs, notes indexed by the real index_vault.py, and HOME pointed at a temporary
directory. Run standalone:

    python3 _bin/mcp_server_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SERVER = os.path.join(REPO, "integrations", "mcp", "server.py")

ok, fail = [], []
TMP = []
FAKE_KEY = "AKIA" + "QRSTUVWXYZABCDEF"


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


STUBS = {
    "compass.py": 'import json, os, sys\nd = json.loads(sys.stdin.read() or "{}")\n'
                  'print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": '
                  '"COMPASS sid=%s env=%s" % (d.get("session_id"), os.environ.get("BRAIN_SESSION_ID"))}}))\n',
    "session_end.py": 'import os, sys\nopen(os.path.join(os.environ["BRAIN_VAULT"], "_index", "session_end_stub.json"), "w")'
                      '.write(sys.stdin.read())\n',
    "vault_sync.py": 'import sys\nprint("vault_sync stub ran %s" % " ".join(sys.argv[1:]))\n',
    "doctor.py": 'print("doctor stub report")\n',
    "presence.py": 'pass\n',
    "lease.py": 'pass\n',
}


def note(vault, rel, title, body, ntype="knowledge"):
    path = os.path.join(vault, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("---\nid: %s\ntitle: %s\ntype: %s\narea: [harness]\nprojects: []\ntags: []\nstatus: active\n"
                 "confidence: high\nsource: agent\nprovenance: test\nupdated: 2026-09-15\nsupersedes: []\n---\n\n%s\n"
                 % (os.path.splitext(os.path.basename(rel))[0], title, ntype, body))


def build_vault():
    root = tempfile.mkdtemp(prefix="mcp-test-")
    TMP.append(root)
    vault, home = os.path.join(root, "vault"), os.path.join(root, "home")
    os.makedirs(home)
    shutil.copytree(HERE, os.path.join(vault, "_bin"), ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name, body in STUBS.items():
        with open(os.path.join(vault, "_bin", name), "w") as fh:
            fh.write(body)
    for d in ("00-Inbox", "_index"):
        os.makedirs(os.path.join(vault, d), exist_ok=True)
    note(vault, "30-Knowledge/2026-09-01-decision-credentials-live-in-keepass.md",
         "Decision: credentials live in the KeePass database",
         "Every credential is stored in the KeePass kdbx database. Notes keep only kp references.", "decision")
    note(vault, "30-Knowledge/2026-09-03-reference-sourdough-starter.md",
         "Reference: sourdough starter feeding", "Flour and water ratios for a sourdough starter.")
    env = dict(os.environ, HOME=home, BRAIN_VAULT=vault)
    for k in ("BRAIN_STATE", "BRAIN_SESSION_ID", "BRAIN_OFF"):
        env.pop(k, None)
    subprocess.run([sys.executable, os.path.join(vault, "_bin", "index_vault.py"), "--full"], env=env,
                   capture_output=True, text=True, timeout=120)
    return vault, env


def converse(vault, env, messages):
    lines = [m if isinstance(m, str) else json.dumps(m) for m in messages]
    p = subprocess.run([sys.executable, SERVER, "--vault", vault], input="\n".join(lines) + "\n", env=env,
                       capture_output=True, text=True, timeout=180)
    out = [l for l in p.stdout.splitlines() if l.strip()]
    parsed, bad = [], []
    for l in out:
        try:
            parsed.append(json.loads(l))
        except ValueError:
            bad.append(l)
    return {m.get("id"): m for m in parsed}, parsed, bad, p


def call(i, name, arguments=None):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": arguments or {}}}


def text_of(resp):
    return "".join(c.get("text", "") for c in (resp.get("result") or {}).get("content", []))


def main():
    if not os.path.isfile(SERVER):
        check("integrations/mcp/server.py exists", False, SERVER)
        return finish()
    vault, env = build_vault()
    inbox_note = "00-Inbox/2026-09-15-mcp-note.md"
    by_id, parsed, bad, p = converse(vault, env, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        "{this is not json",
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
        call(10, "recall", {"query": "where are credentials stored keepass"}),
        call(11, "recall", {"query": "kubernetes ingress rate limiting in staging"}),
        call(12, "recall", {}),
        call(13, "search", {"query": "keepass"}),
        call(14, "get_note", {"path": "30-Knowledge/2026-09-01-decision-credentials-live-in-keepass.md"}),
        call(15, "get_note", {"path": "../outside.txt"}),
        call(16, "write_note", {"path": "00-Inbox/2026-09-15-mcp-note", "title": "MCP note",
                                "content": "hello from mcp\nkey %s\n" % FAKE_KEY, "type": "note"}),
        call(17, "append_note", {"path": inbox_note, "content": "appended over mcp"}),
        call(18, "sync"),
        call(19, "status"),
        call(20, "session_start"),
        call(21, "session_end"),
        call(22, "list_recent", {"limit": 3}),
        call(30, "no_such_tool"),
        {"jsonrpc": "2.0", "id": 31, "method": "resources/unknown"},
    ])
    check("stdout carries only JSON-RPC lines", not bad, bad[:3])
    init = by_id.get(1, {}).get("result", {})
    check("initialize answers with the client's protocol version and a tools capability",
          init.get("protocolVersion") == "2025-06-18" and "tools" in init.get("capabilities", {})
          and init.get("serverInfo", {}).get("name") == "brain", init)
    check("a notification gets no reply", len(parsed) == len(by_id) and None not in by_id, [m.get("id") for m in parsed])
    check("a bad JSON line is ignored and the server keeps answering", 3 in by_id and by_id[3].get("result") == {})

    names = [t["name"] for t in by_id.get(2, {}).get("result", {}).get("tools", [])]
    check("the tool list covers knowledge, writes, maintenance and sessions",
          set(names) >= {"recall", "search", "list_recent", "get_note", "write_note", "append_note",
                         "reindex", "sync", "status", "session_start", "session_end"}, names)
    check("no tool hands out credentials", not any(w in n for n in names for w in ("secret", "kp", "credential", "password")),
          names)

    recall = text_of(by_id.get(10, {}))
    check("recall renders the covering note the way the hook injects it",
          "2026-09-01-decision-credentials-live-in-keepass.md" in recall
          and "Notes retrieved from the Brain vault" in recall and "sourdough" not in recall, recall)
    miss = by_id.get(11, {}).get("result", {})
    check("recall on a topic the vault does not cover says so, without an error",
          not miss.get("isError") and "nothing" in text_of(by_id[11]).lower(), miss)
    check("recall without a query is an error result", by_id.get(12, {}).get("result", {}).get("isError"))
    check("search lists matches through query.py", "credentials-live-in-keepass" in text_of(by_id.get(13, {})),
          text_of(by_id.get(13, {})))
    check("get_note returns the note", "Every credential is stored" in text_of(by_id.get(14, {})))
    check("get_note refuses a path that escapes the vault",
          by_id.get(15, {}).get("result", {}).get("isError") and "escapes" in text_of(by_id[15]), by_id.get(15))

    written = os.path.join(vault, inbox_note)
    body = open(written).read() if os.path.exists(written) else ""
    check("write_note creates the note through vw.py, with frontmatter",
          not by_id.get(16, {}).get("result", {}).get("isError") and "title: MCP note" in body
          and "hello from mcp" in body, (by_id.get(16), body[:200]))
    check("and the credential in its body is redacted", FAKE_KEY not in body and "REDACTED" in body, body)
    check("append_note appends through vw.py", "appended over mcp" in body, body)
    check("sync shells out to vault_sync.py", "vault_sync stub ran" in text_of(by_id.get(18, {})), by_id.get(18))
    check("status shells out to doctor.py", "doctor stub report" in text_of(by_id.get(19, {})), by_id.get(19))
    start = text_of(by_id.get(20, {}))
    check("session_start returns the startup context from compass.py",
          start.startswith("COMPASS sid=mcp-"), start)
    check("under one session id the server exported for its process tree",
          start.split("sid=")[1].split()[0] == start.split("env=")[1].strip(), start)
    stub = os.path.join(vault, "_index", "session_end_stub.json")
    ended = json.load(open(stub)) if os.path.exists(stub) else {}
    check("session_end hands the same session id to session_end.py",
          ended.get("session_id") == start.split("env=")[1].strip(), ended)
    check("list_recent answers", not by_id.get(22, {}).get("result", {}).get("isError"), by_id.get(22))
    check("an unknown tool is a JSON-RPC method-not-found error", by_id.get(30, {}).get("error", {}).get("code") == -32601)
    check("an unknown method is too", by_id.get(31, {}).get("error", {}).get("code") == -32601)
    return finish()


def finish():
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
