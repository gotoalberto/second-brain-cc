#!/usr/bin/env python3
"""Tests for integrations/cli/brain — Brain from any shell, agent or person.

Runs the CLI as a subprocess against a temporary vault: a copy of _bin with the scripts
that would reach the network or the real vault replaced by stubs, notes indexed by the
real index_vault.py, HOME temporary. Run standalone:

    python3 _bin/brain_cli_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CLI = os.path.join(REPO, "integrations", "cli", "brain")

ok, fail = [], []
TMP = []

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
    "hook_echo.py": 'import json, os, sys\nd = json.loads(sys.stdin.read() or "{}")\n'
                    'print("HOOK event=%s sid=%s source=%s tool=%s cwd=%s argv=%s" % (d.get("hook_event_name"), '
                    'd.get("session_id"), d.get("source"), d.get("tool_name"), d.get("cwd"), sys.argv[1:]))\n'
                    'sys.stderr.write("hook said something on stderr\\n")\n'
                    'sys.exit(int(os.environ.get("HOOK_EXIT", "0")))\n',
}
EVENTS = {"version": 1, "events": [
    {"id": "pre-write-gate", "description": "gate", "handler": "gate_write",
     "triggers": [{"kind": "claude-hook", "event": "PreToolUse", "matcher": "Bash", "command": "hook_echo.py --gate"},
                  {"kind": "git-hook", "hook": "pre-commit", "command": "events_core/git_pre_commit.py"}]},
    {"id": "reindex", "description": "index", "handler": "index_vault",
     "triggers": [{"kind": "file-watch", "action": "index-trigger", "command": "index_vault.py"},
                  {"kind": "cli", "command": "brain index"}]}]}
PROMPT = "where are credentials stored keepass"


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def note(vault, rel, title, body, ntype="knowledge"):
    path = os.path.join(vault, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("---\nid: %s\ntitle: %s\ntype: %s\narea: [harness]\nprojects: []\ntags: []\nstatus: active\n"
                 "confidence: high\nsource: agent\nprovenance: test\nupdated: 2026-09-15\nsupersedes: []\n---\n\n%s\n"
                 % (os.path.splitext(os.path.basename(rel))[0], title, ntype, body))


def build_vault():
    root = tempfile.mkdtemp(prefix="brain-cli-test-")
    TMP.append(root)
    vault, home = os.path.join(root, "vault"), os.path.join(root, "home")
    os.makedirs(home)
    shutil.copytree(HERE, os.path.join(vault, "_bin"), ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name, body in STUBS.items():
        with open(os.path.join(vault, "_bin", name), "w") as fh:
            fh.write(body)
    for d in ("00-Inbox", "_index", "90-Meta"):
        os.makedirs(os.path.join(vault, d), exist_ok=True)
    with open(os.path.join(vault, "90-Meta", "events.json"), "w") as fh:
        json.dump(EVENTS, fh)
    note(vault, "30-Knowledge/2026-09-01-decision-credentials-live-in-keepass.md",
         "Decision: credentials live in the KeePass database",
         "Every credential is stored in the KeePass kdbx database. Notes keep only kp references.", "decision")
    env = dict(os.environ, HOME=home, BRAIN_VAULT=vault)
    for k in ("BRAIN_STATE", "BRAIN_SESSION_ID", "BRAIN_OFF"):
        env.pop(k, None)
    subprocess.run([sys.executable, os.path.join(vault, "_bin", "index_vault.py"), "--full"], env=env,
                   capture_output=True, text=True, timeout=120)
    return vault, env


def brain(env, *args, stdin=""):
    return subprocess.run([CLI] + list(args), env=env, input=stdin, capture_output=True, text=True, timeout=180)


def main():
    if not os.path.isfile(CLI) or not os.access(CLI, os.X_OK):
        check("integrations/cli/brain exists and is executable", False, CLI)
        return finish()
    vault, env = build_vault()

    p = brain(env, "--help")
    check("--help exits 0 and lists the commands",
          p.returncode == 0 and all(c in p.stdout for c in ("recall", "search", "get", "new", "append", "sync",
                                                            "session-start", "session-end", "mcp")), p.stdout[:400])

    p = brain(env, "recall", *PROMPT.split())
    check("recall prints the covering note", p.returncode == 0 and "credentials-live-in-keepass" in p.stdout,
          (p.returncode, p.stdout, p.stderr))
    shared = subprocess.run([sys.executable, "-c",
                             "import sys; sys.path.insert(0, %r)\nimport brainlib as B, retrieve_core as R\n"
                             "c = B.db(); sys.stdout.write(R.search_and_render(c, %r)); c.close()"
                             % (os.path.join(vault, "_bin"), PROMPT)],
                            env=env, capture_output=True, text=True, timeout=60).stdout
    check("with exactly the rendering the hook uses (retrieve_core)", p.stdout.strip() == shared.strip() and shared,
          (p.stdout, shared))
    p = brain(env, "recall")
    check("recall without terms is a usage error", p.returncode == 2, p.returncode)
    p = brain(env, "recall", "kubernetes", "ingress", "staging")
    check("recall on an uncovered topic says so and exits 0", p.returncode == 0 and "nothing" in p.stdout.lower(),
          (p.returncode, p.stdout))

    p = brain(env, "search", "keepass")
    check("search lists matches through query.py", p.returncode == 0 and "credentials-live-in-keepass" in p.stdout,
          (p.returncode, p.stdout, p.stderr))
    p = brain(env, "get", "30-Knowledge/2026-09-01-decision-credentials-live-in-keepass.md")
    check("get prints a note", p.returncode == 0 and "Every credential is stored" in p.stdout)
    p = brain(env, "get", "../outside.txt")
    check("get refuses a path that escapes the vault", p.returncode == 1 and "escapes" in p.stderr, (p.returncode, p.stderr))

    rel = "00-Inbox/2026-09-15-cli-note.md"
    p = brain(env, "new", rel, "--title", "CLI note", "--type", "note", stdin="written from the cli\n")
    body = open(os.path.join(vault, rel)).read() if os.path.exists(os.path.join(vault, rel)) else ""
    check("new writes a note through vw.py", p.returncode == 0 and "title: CLI note" in body and "written from the cli" in body,
          (p.returncode, p.stderr, body[:200]))
    p = brain(env, "append", rel, stdin="appended from the cli\n")
    check("append appends through vw.py", p.returncode == 0 and "appended from the cli" in open(os.path.join(vault, rel)).read())

    p = brain(env, "sync")
    check("sync runs vault_sync.py", "vault_sync stub ran" in p.stdout, (p.stdout, p.stderr))
    p = brain(env, "status")
    check("status runs doctor.py", "doctor stub report" in p.stdout, p.stdout)

    p = brain(env, "session-start")
    check("session-start prints compass.py's startup context", p.stdout.startswith("COMPASS sid=cli-"), (p.stdout, p.stderr))
    sid = p.stdout.split("env=")[1].strip() if "env=" in p.stdout else ""
    check("under a session id the CLI exported for its own process tree",
          sid.startswith("cli-") and p.stdout.split("sid=")[1].split()[0] == sid, p.stdout)
    env2 = dict(env, BRAIN_SESSION_ID="agent-session-9")
    p = brain(env2, "session-start")
    check("a session id already exported by the caller is kept", "sid=agent-session-9 env=agent-session-9" in p.stdout,
          p.stdout)
    p = brain(env2, "session-end")
    stub = os.path.join(vault, "_index", "session_end_stub.json")
    check("session-end hands the session id to session_end.py",
          p.returncode == 0 and os.path.exists(stub) and json.load(open(stub)).get("session_id") == "agent-session-9")

    print("\n== brain hook ==")
    p = brain(env, "--help")
    check("--help lists brain hook and warns to verify the handler's JSON shape",
          "hook <event-id>" in p.stdout and "verify" in p.stdout.lower(), p.stdout)
    p = brain(env, "hook", "pre-write-gate")
    check("brain hook runs the event's claude-hook command with its arguments",
          p.returncode == 0 and "HOOK event=PreToolUse" in p.stdout and "argv=['--gate']" in p.stdout,
          (p.returncode, p.stdout, p.stderr))
    check("with the stdin JSON a Claude Code hook gets: session id, cwd, source",
          "sid=cli-" in p.stdout and "source=cli" in p.stdout and "cwd=" in p.stdout, p.stdout)
    check("the handler's stderr passes through", "hook said something on stderr" in p.stderr, p.stderr)
    p = brain(env, "hook", "pre-write-gate", "--payload", json.dumps({"tool_name": "Bash"}))
    check("--payload adds the event's own fields", "tool=Bash" in p.stdout, p.stdout)
    p = brain(dict(env, HOOK_EXIT="2"), "hook", "pre-write-gate")
    check("the handler's exit code is brain hook's (2 blocks, as in Claude Code)", p.returncode == 2, p.returncode)
    p = brain(env, "hook", "reindex")
    check("an event with no hook command says so and names what does trigger it",
          p.returncode == 2 and "no hook command" in p.stderr and "file-watch" in p.stderr, (p.returncode, p.stderr))
    p = brain(env, "hook", "no-such-event")
    check("an unknown event is a usage error naming the known ones",
          p.returncode == 2 and "unknown event" in p.stderr and "pre-write-gate" in p.stderr, (p.returncode, p.stderr))
    p = brain(env, "hook")
    check("brain hook without an event is a usage error", p.returncode == 2, p.returncode)
    p = brain(env, "hook", "pre-write-gate", "--payload", "not json")
    check("a payload that is not a JSON object is a usage error", p.returncode == 2 and "payload" in p.stderr,
          (p.returncode, p.stderr))

    p = brain(env, "bogus")
    check("an unknown command is a usage error", p.returncode == 2 and "unknown command" in p.stderr, (p.returncode, p.stderr))

    p = brain(env, "mcp", stdin=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                            "params": {"protocolVersion": "2025-06-18"}}) + "\n")
    reply = json.loads(p.stdout.splitlines()[0]) if p.stdout.strip() else {}
    check("mcp runs the MCP server on stdio", reply.get("result", {}).get("serverInfo", {}).get("name") == "brain",
          (p.stdout, p.stderr))
    return finish()


def finish():
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
