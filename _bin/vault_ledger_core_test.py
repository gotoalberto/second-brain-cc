#!/usr/bin/env python3
"""Tests for vault_ledger_core and vault_ledger.py — which notes a session gets credit for.

The pure half is tested with literal mtimes. vault_ledger.py itself runs as a subprocess
against a temporary vault with HOME pointed at a temporary directory, so its database,
markers and state are all temporary: once as the Claude Code hook (behaviour unchanged)
and once through the new command line the file-watch job uses. Run standalone:

    python3 _bin/vault_ledger_core_test.py
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []
TMP = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def tmpdir():
    d = tempfile.mkdtemp(prefix="ledger-test-")
    TMP.append(d)
    return d


def write(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    return path


def test_core(L):
    print("\n== vault_ledger_core ==")
    check("with no marker the window opens MAX_WINDOW seconds back",
          L.window_since("", now=1000.0) == 1000.0 - L.MAX_WINDOW)
    check("a recent marker starts the window", L.window_since("950.5", now=1000.0) == 950.5)
    check("an old marker is capped at MAX_WINDOW",
          L.window_since("100", now=1000.0) == 1000.0 - L.MAX_WINDOW)
    check("a garbled marker is treated as none", L.window_since("garbage", now=1000.0) == 1000.0 - L.MAX_WINDOW)
    check("the window cap is still two minutes", L.MAX_WINDOW == 120.0)

    mtimes = {"/v/30-Knowledge/a.md": 150.0, "/v/30-Knowledge/b.md": 100.0,
              "/v/10-Projects/c.md": 99.0, "/v/30-Knowledge/pulled.md": 200.0}
    got = L.credited_notes(since=100.0, mtimes=mtimes, git_touched={"/v/30-Knowledge/pulled.md"})
    check("only notes strictly newer than the window start are credited", got == ["/v/30-Knowledge/a.md"], got)
    check("notes a git pull rewrote are never credited to a session",
          "/v/30-Knowledge/pulled.md" not in got)

    notes = ["/v/10-Projects/p.md", "/v/70-Entities/ok.md", "/v/30-Knowledge/k.md", "/v/70-Entities/e.md"]
    raw = L.unlocked_protected(notes, vault="/v", wrote_by_vw=lambda p: p.endswith("ok.md"))
    check("protected notes not written by vw.py are singled out, in order",
          raw == ["/v/10-Projects/p.md", "/v/70-Entities/e.md"], raw)
    msg = L.unlocked_notice(raw, vault="/v")
    check("the notice counts them, names them relative to the vault and points at vw.py",
          msg.startswith("Brain: 2 shared note(s)") and "10-Projects/p.md" in msg and "vw.py" in msg
          and "/v/" not in msg, msg)


def env_for(vault, home):
    env = dict(os.environ, HOME=home, BRAIN_VAULT=vault)
    env.pop("BRAIN_OFF", None)
    env.pop("BRAIN_STATE", None)
    return env


def rows(vault):
    db = os.path.join(vault, "_index", "vault.db")
    if not os.path.exists(db):
        return []
    con = sqlite3.connect(db)
    try:
        return sorted(con.execute("SELECT sid, path FROM vault_writes").fetchall())
    finally:
        con.close()


def test_cli():
    print("\n== vault_ledger.py --sid --paths (the file-watch job's entry) ==")
    root = tmpdir()
    vault, home = os.path.join(root, "vault"), os.path.join(root, "home")
    os.makedirs(home)
    write(os.path.join(vault, "30-Knowledge", "a.md"))
    write(os.path.join(vault, "10-Projects", "b.md"))
    p = subprocess.run([sys.executable, os.path.join(HERE, "vault_ledger.py"), "--sid", "system", "--paths",
                        "30-Knowledge/a.md", "10-Projects/b.md", "30-Knowledge/missing.md"],
                       env=env_for(vault, home), capture_output=True, text=True, timeout=60)
    got = rows(vault)
    check("the given notes are credited to the given session id",
          p.returncode == 0 and got == [("system", os.path.join(vault, "10-Projects", "b.md")),
                                        ("system", os.path.join(vault, "30-Knowledge", "a.md"))],
          (p.returncode, p.stderr, got))
    check("a path that does not exist is not credited", not any("missing" in r[1] for r in got))


def test_hook_unchanged():
    print("\n== vault_ledger.py as the Claude Code PostToolUse hook ==")
    root = tmpdir()
    vault, home = os.path.join(root, "vault"), os.path.join(root, "home")
    os.makedirs(os.path.join(vault, "30-Knowledge"))
    os.makedirs(home)
    env = env_for(vault, home)
    payload = json.dumps({"session_id": "hooktest-session-1"})

    def hook():
        return subprocess.run([sys.executable, os.path.join(HERE, "vault_ledger.py")], input=payload,
                              env=env, capture_output=True, text=True, timeout=60)

    p = hook()
    check("the first call only opens the window", p.returncode == 0 and rows(vault) == [], (p.returncode, p.stderr))
    time.sleep(0.05)
    write(os.path.join(vault, "30-Knowledge", "note.md"))
    write(os.path.join(vault, "10-Projects", "raw.md"))
    p = hook()
    got = rows(vault)
    credited = sorted(os.path.relpath(r[1], vault) for r in got)
    check("notes written since are credited to the hook's session",
          p.returncode == 0 and credited == ["10-Projects/raw.md", "30-Knowledge/note.md"]
          and all(r[0] != "system" for r in got), (p.stderr, got))
    check("a protected note written without vw.py still produces the systemMessage",
          "systemMessage" in p.stdout and "10-Projects/raw.md" in p.stdout and "vw.py" in p.stdout, p.stdout)
    p = subprocess.run([sys.executable, os.path.join(HERE, "vault_ledger.py")], input="{}",
                       env=env, capture_output=True, text=True, timeout=60)
    check("with no session id the hook credits nothing and exits 0", p.returncode == 0 and not p.stdout.strip())


def main():
    try:
        import vault_ledger_core as L
    except Exception as exc:
        check("vault_ledger_core imports", False, "%s: %s" % (type(exc).__name__, exc))
        return finish()
    for t in (lambda: test_core(L), test_cli, test_hook_unchanged):
        try:
            t()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            check("a test section ran to the end", False, "%s: %s" % (type(exc).__name__, exc))
    return finish()


def finish():
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
