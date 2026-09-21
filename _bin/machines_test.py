#!/usr/bin/env python3
"""Tests for machines.py: the machine registry's thin disk and subprocess half.

Every folder is temporary, `claude auth status` is a fake `run`, and BRAIN_MACHINE_KEY forces the
identity, so no real hostname, uuid or Claude account is read or written. The rules themselves
are in machines_core_test.py. Run standalone:

    python3 _bin/machines_test.py
"""
import io
import contextlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import machines as M
import machines_core as C

ok, fail = [], []
TMP = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def tmpdir():
    d = tempfile.mkdtemp(prefix="machines-test-")
    TMP.append(d)
    return d


def fake_run(stdout, rc=0):
    calls = []

    def run(cmd):
        calls.append(cmd)
        return rc, stdout, ""
    run.calls = calls
    return run


LOGGED_IN = json.dumps({"loggedIn": True, "email": "someone@example.com", "orgName": ""})


def test_registry_dir():
    root = tmpdir()
    shared = os.path.join(root, "shared")
    env = {"BRAIN_SHARED_DIR": shared, "BRAIN_STATE": os.path.join(root, "state")}
    check("with a shared path configured, the registry lives under it",
          M.registry_dir(env, home=root) == os.path.join(shared, "machines"), M.registry_dir(env, home=root))
    env = {"BRAIN_STATE": os.path.join(root, "state")}
    check("with none, it falls back to this machine's state directory",
          M.registry_dir(env, home=root, config_path=os.path.join(root, "none.json"))
          == os.path.join(root, "state", "machines"))


def test_claude_account():
    run = fake_run(LOGGED_IN)
    check("the account comes from `claude auth status`",
          M.claude_account(run) == ("someone@example.com", "") and run.calls == [["claude", "auth", "status"]],
          run.calls)

    def broken(cmd):
        raise OSError("no such file")
    check("no CLI at all is unknown, never an exception", M.claude_account(broken) == (C.UNKNOWN_ACCOUNT, ""))
    check("a failing CLI is unknown", M.claude_account(fake_run("", rc=1)) == (C.UNKNOWN_ACCOUNT, ""))


def test_describe():
    env = {"BRAIN_MACHINE_KEY": "laptop-a-aaaaaaaa", "USER": "someone"}
    got = M.describe(environ=env, run=fake_run(LOGGED_IN), platform="linux")
    check("a forced key is used as-is and its fragment becomes id8",
          got["key"] == "laptop-a-aaaaaaaa" and got["id8"] == "aaaaaaaa", got)
    check("the label is the key without its fragment", got["label"] == "laptop-a", got)
    check("os, user and account are filled", got["os"] == "linux" and got["user"] == "someone"
          and got["claude_account"] == "someone@example.com", got)
    got = M.describe(environ={"BRAIN_MACHINE_KEY": "box", "USER": "u"}, run=fake_run(LOGGED_IN), platform="darwin")
    check("a key with no fragment has no id8, and macOS is named as such",
          got["id8"] == "" and got["label"] == "box" and got["os"] == "macos", got)
    check("nothing in a description is the full uuid", all(len(v) < 36 for v in got.values()), got)


def test_register_and_read():
    folder = os.path.join(tmpdir(), "machines")
    info = {"key": "laptop-a-aaaaaaaa", "id8": "aaaaaaaa", "label": "laptop-a", "os": "linux", "user": "u",
            "claude_account": "someone@example.com", "claude_org": ""}
    changed, path = M.register(today="2026-01-02", info=info, folder=folder)
    check("a first registration writes <folder>/<key>.json",
          changed and path == os.path.join(folder, "laptop-a-aaaaaaaa.json") and os.path.isfile(path), path)
    check("the file is private to the user (0600)", oct(os.stat(path).st_mode & 0o777) == "0o600",
          oct(os.stat(path).st_mode & 0o777))
    before = os.stat(path).st_mtime_ns
    changed, _ = M.register(today="2026-01-02", info=info, folder=folder)
    check("registering again the same day with nothing new writes nothing",
          not changed and os.stat(path).st_mtime_ns == before)
    changed, _ = M.register(today="2026-01-03", info=info, folder=folder)
    rec = C.parse(open(path).read())
    check("the next day refreshes last_seen and keeps first_seen",
          changed and rec["last_seen"] == "2026-01-03" and rec["first_seen"] == "2026-01-02", rec)
    renamed = dict(info, key="laptop-new-aaaaaaaa", label="laptop-new")
    changed, path2 = M.register(today="2026-01-04", info=renamed, folder=folder)
    rec2 = C.parse(open(path2).read())
    check("a rename writes a new file and carries first_seen over",
          changed and path2 != path and rec2["first_seen"] == "2026-01-02", rec2)
    check("the old file is left where it is", os.path.isfile(path))
    with open(os.path.join(folder, "junk.json"), "w") as fh:
        fh.write("{not json")
    with open(os.path.join(folder, "notes.txt"), "w") as fh:
        fh.write("ignored")
    rows = M.read_all(folder)
    check("read_all returns every valid record and skips the rest",
          sorted(r["key"] for r in rows) == ["laptop-a-aaaaaaaa", "laptop-new-aaaaaaaa"], rows)
    machines = M.list_machines(folder)
    check("list_machines collapses the two records of one machine",
          len(machines) == 1 and machines[0]["entry"]["key"] == "laptop-new-aaaaaaaa"
          and machines[0]["aliases"] == ["laptop-a-aaaaaaaa"], machines)
    check("a missing folder is an empty registry, not an error", M.read_all(os.path.join(folder, "nope")) == [])
    left = [n for n in os.listdir(folder) if ".tmp." in n]
    check("no temporary file is left behind", left == [], left)


def test_here():
    folder = os.path.join(tmpdir(), "machines")
    base = {"id8": "aaaaaaaa", "label": "laptop-a", "os": "linux", "user": "u",
            "claude_account": "someone@example.com", "claude_org": ""}
    M.register(today="2026-01-01", info=dict(base, key="old-aaaaaaaa"), folder=folder)
    M.register(today="2026-01-05", info=dict(base, key="laptop-a-aaaaaaaa"), folder=folder)
    M.register(today="2026-01-06", info=dict(base, key="laptop-b-bbbbbbbb", id8="bbbbbbbb"), folder=folder)
    env = {"BRAIN_MACHINE_KEY": "laptop-a-aaaaaaaa"}
    got = M.here(folder=folder, environ=env)
    check("here() is this machine's newest record", got and got["key"] == "laptop-a-aaaaaaaa", got)
    check("an unregistered machine has none", M.here(folder=folder, environ={"BRAIN_MACHINE_KEY": "zz-cccccccc"}) is None)


def test_main():
    root = tmpdir()
    env = {"BRAIN_MACHINE_KEY": "laptop-a-aaaaaaaa", "USER": "u", "BRAIN_SHARED_DIR": os.path.join(root, "shared")}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = M.main(["register"], environ=env, run=fake_run(LOGGED_IN), today="2026-01-02")
    check("`register` writes this machine's record and says so",
          rc == 0 and "registered" in buf.getvalue()
          and os.path.isfile(os.path.join(root, "shared", "machines", "laptop-a-aaaaaaaa.json")), buf.getvalue())
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = M.main([], environ=env, run=fake_run(LOGGED_IN), today="2026-01-02")
    check("the default command lists the registry with this machine starred",
          rc == 0 and "* laptop-a-aaaaaaaa" in buf.getvalue() and "1 machine(s)" in buf.getvalue(), buf.getvalue())
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = M.main(["here"], environ=env, run=fake_run(LOGGED_IN), today="2026-01-02")
    check("`here` prints this machine's record as JSON",
          rc == 0 and json.loads(buf.getvalue())["key"] == "laptop-a-aaaaaaaa", buf.getvalue())
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = M.main(["bogus"], environ=env, run=fake_run(LOGGED_IN), today="2026-01-02")
    check("an unknown command is exit 2 with the usage", rc == 2 and "register" in buf.getvalue())


def test_register_daily():
    root = tmpdir()
    env = {"BRAIN_MACHINE_KEY": "laptop-a-aaaaaaaa", "USER": "u", "BRAIN_SHARED_DIR": os.path.join(root, "shared"),
           "BRAIN_STATE": os.path.join(root, "state")}
    run = fake_run(LOGGED_IN)
    got = M.register_daily(environ=env, run=run, today="2026-01-02")
    record = os.path.join(root, "shared", "machines", "laptop-a-aaaaaaaa.json")
    check("the daily registration writes this machine's record", got == "registered" and os.path.isfile(record),
          got)
    check("and leaves a stamp in this machine's state", os.path.isfile(os.path.join(root, "state", M.DAILY_STAMP)))
    calls = len(run.calls)
    got = M.register_daily(environ=env, run=run, today="2026-01-02")
    check("a second run the same day asks nothing and writes nothing",
          got == "already today" and len(run.calls) == calls, (got, run.calls))
    got = M.register_daily(environ=env, run=run, today="2026-01-03")
    check("the next day registers again", got in ("registered", "unchanged") and len(run.calls) > calls, got)
    blocker = os.path.join(root, "a-file")
    with open(blocker, "w") as fh:
        fh.write("in the way")
    broken = dict(env, BRAIN_SHARED_DIR=os.path.join(blocker, "shared"), BRAIN_STATE=os.path.join(blocker, "state"))
    try:
        got, raised = M.register_daily(environ=broken, run=run, today="2026-01-04"), None
    except Exception as exc:
        got, raised = None, exc
    check("a registry that cannot be written is reported, never raised",
          raised is None and str(got).startswith("failed"), (got, raised))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = M.main(["register", "--daily"], environ=broken, run=run, today="2026-01-04")
    check("`register --daily` exits 0 even when it failed, and says what happened",
          rc == 0 and "machine registry: failed" in buf.getvalue(), buf.getvalue())


def main():
    for t in (test_registry_dir, test_claude_account, test_describe, test_register_and_read, test_here, test_main,
              test_register_daily):
        print("\n== %s ==" % t.__name__)
        try:
            t()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            check("%s ran without raising" % t.__name__, False, repr(exc))
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
