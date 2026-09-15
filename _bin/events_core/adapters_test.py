#!/usr/bin/env python3
"""Tests for events_core.adapters — the event layer's contact with the machine.

Temporary directories with explicit mtimes, a temporary state file, /bin/echo and
/bin/sleep as processes, a throwaway git repository, a temporary alert file. Nothing
reads the real vault, runs `ps`, or touches ~/.claude. Run standalone:

    python3 _bin/events_core/adapters_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[0] = os.path.dirname(HERE)

ok, fail = [], []
TMP = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def tmpdir():
    d = tempfile.mkdtemp(prefix="events-adapters-")
    TMP.append(d)
    return d


def write(path, text="x", mtime=None, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    if mode is not None:
        os.chmod(path, mode)
    return path


def git(cwd, *args):
    return subprocess.run(["/usr/bin/git", "-c", "user.name=t", "-c", "user.email=t@example.com",
                           "-c", "init.defaultBranch=main"] + list(args),
                          cwd=cwd, capture_output=True, text=True)


def test_snapshot():
    print("\n== FsSnapshot ==")
    v = tmpdir()
    write(os.path.join(v, "30-Knowledge", "a.md"), mtime=1000)
    write(os.path.join(v, "30-Knowledge", "sub", "b.md"), mtime=2000)
    write(os.path.join(v, "30-Knowledge", "__pycache__", "c.pyc"), mtime=3000)
    write(os.path.join(v, "_bin", "x.py"), mtime=4000)
    write(os.path.join(v, "80-Private", "secret.md"), mtime=5000)
    write(os.path.join(v, "_bin", ".git", "HEAD"), mtime=6000)
    write(os.path.join(v, "README.md"), mtime=7000)
    snap = AD.FsSnapshot(v).read(["30-Knowledge", "_bin", "README.md", "does-not-exist"])
    check("only the listed paths are read, recursively, with their mtimes",
          snap == {"30-Knowledge/a.md": 1000.0, "30-Knowledge/sub/b.md": 2000.0,
                   "_bin/x.py": 4000.0, "README.md": 7000.0}, snap)
    check("a folder not listed (80-Private) is never read", not any(p.startswith("80-Private") for p in snap))
    check("caches and git internals are skipped", not any("__pycache__" in p or ".git" in p for p in snap))


def test_state_runner_files():
    print("\n== JsonWatchState, SubprocessRunner, VaultFiles, SystemClock ==")
    d = tmpdir()
    path = os.path.join(d, "state", "watch.json")
    AD.JsonWatchState(path).save({"snapshot": {"a.md": 1.0}, "memory": {"sync_pending": True}})
    check("watch state persists across instances",
          AD.JsonWatchState(path).load() == {"snapshot": {"a.md": 1.0}, "memory": {"sync_pending": True}})
    write(path, "garbage")
    check("corrupt watch state loads as empty", AD.JsonWatchState(path).load() == {})

    r = AD.SubprocessRunner()
    rc, out, err = r.run(["/bin/echo", "hello", "two words"], timeout=10)
    check("a command runs as argv and its output comes back", rc == 0 and out.strip() == "hello two words", (rc, out, err))
    rc, _, err = r.run(["/nonexistent/tool"], timeout=10)
    check("a missing command is exit 127, not an exception", rc == 127 and err, (rc, err))
    rc, _, _ = r.run(["/bin/sleep", "5"], timeout=1)
    check("a command past its timeout is exit 124", rc == 124, rc)

    v = tmpdir()
    files = AD.VaultFiles(v)
    check("a missing file reads as None", files.read("githooks/pre-commit") is None)
    files.write("githooks/pre-commit", "#!/bin/sh\nexit 0\n", executable=True)
    full = os.path.join(v, "githooks", "pre-commit")
    check("a written file has its content", files.read("githooks/pre-commit") == "#!/bin/sh\nexit 0\n")
    check("and is executable when asked", os.access(full, os.X_OK))
    files.write("AGENTS.md", "hello\n")
    check("a plain file is not executable", not os.access(os.path.join(v, "AGENTS.md"), os.X_OK))
    check("no temporary file is left behind", not [f for f in os.listdir(os.path.join(v, "githooks")) if f.endswith(".tmp")])
    check("the clock returns epoch seconds", AD.SystemClock().now() > 1.7e9)


def test_session_id():
    print("\n== EnvThenProcessTreeSessionId ==")
    s = AD.EnvThenProcessTreeSessionId(environ={"BRAIN_SESSION_ID": "cli-4242"}, claude_pid=lambda: 999)
    check("BRAIN_SESSION_ID wins", s.resolve() == "cli-4242")
    s = AD.EnvThenProcessTreeSessionId(environ={}, claude_pid=lambda: 31337)
    check("else the Claude Code session process, if there is one", s.resolve() == "31337")
    s = AD.EnvThenProcessTreeSessionId(environ={}, claude_pid=lambda: 0)
    check("else the literal 'system', never a made-up id", s.resolve() == "system")

    def broken():
        raise OSError("ps is gone")

    check("a failing process-tree lookup is 'system' too",
          AD.EnvThenProcessTreeSessionId(environ={}, claude_pid=broken).resolve() == "system")


def test_alert_sink():
    print("\n== GuardianAlertSink ==")
    d = tmpdir()
    path = os.path.join(d, "guardian-raised.json")
    sink = AD.GuardianAlertSink(path=path)
    sink.raise_alert("watch:unsynced", "vault changes unsynced for 61 min")
    data = json.load(open(path))
    check("an alert lands in the guardian's raised-alerts file as a warning",
          data.get("watch:unsynced", {}).get("severity") == "warn"
          and "61 min" in data["watch:unsynced"]["summary"], data)
    sink.clear_alert("watch:unsynced")
    check("and clearing removes it", "watch:unsynced" not in json.load(open(path)))
    blocked = write(os.path.join(d, "a-file"), "in the way")
    try:
        AD.GuardianAlertSink(path=os.path.join(blocked, "raised.json")).raise_alert("k", "s")
        broke = None
    except Exception as exc:
        broke = exc
    check("an alert that cannot be written never raises", broke is None, repr(broke))


def test_git_probe():
    print("\n== GitUnsyncedProbe ==")
    root = tmpdir()
    remote, vault = os.path.join(root, "remote.git"), os.path.join(root, "vault")
    os.makedirs(vault)
    git(root, "init", "-q", "--bare", remote)
    git(vault, "init", "-q")
    write(os.path.join(vault, "a.md"), "a")
    git(vault, "add", "-A")
    git(vault, "commit", "-qm", "one")
    git(vault, "remote", "add", "origin", remote)
    git(vault, "push", "-q", "-u", "origin", "HEAD:main")
    git(vault, "branch", "-q", "--set-upstream-to=origin/main")
    probe = AD.GitUnsyncedProbe(vault, now=lambda: 10_000_000_000.0)
    check("a clean, pushed vault has nothing unsynced", probe.oldest_unsynced_mtime() is None,
          probe.oldest_unsynced_mtime())
    write(os.path.join(vault, "b.md"), "b", mtime=1_700_000_000)
    write(os.path.join(vault, "c.md"), "c", mtime=1_700_000_500)
    check("uncommitted files count from their oldest mtime",
          probe.oldest_unsynced_mtime() == 1_700_000_000.0, probe.oldest_unsynced_mtime())
    git(vault, "add", "-A")
    git(vault, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "two")
    t = probe.oldest_unsynced_mtime()
    check("committed but unpushed work counts from the commit time", t is not None and t > 1_700_000_500, t)
    probe_lone = AD.GitUnsyncedProbe(tmpdir())
    check("a directory that is not a repository reports nothing", probe_lone.oldest_unsynced_mtime() is None)


def test_claude_settings_hooks():
    print("\n== ClaudeSettingsHooks ==")
    d = tmpdir()
    check("no Claude Code config directory is None: nothing to watch",
          AD.ClaudeSettingsHooks(os.path.join(d, "nope")).hooks() is None)
    cfg = os.path.join(d, ".claude")
    os.makedirs(cfg)
    reader = AD.ClaudeSettingsHooks(cfg)
    check("a config directory with no settings.json has no hooks", reader.hooks() == {})
    write(os.path.join(cfg, "settings.json"), json.dumps({"model": "x", "hooks": {"Stop": [{"hooks": []}]}}))
    check("the hooks block is read", reader.hooks() == {"Stop": [{"hooks": []}]})
    write(os.path.join(cfg, "settings.json"), json.dumps({"model": "x"}))
    check("settings without a hooks key have no hooks", reader.hooks() == {})
    write(os.path.join(cfg, "settings.json"), "{broken")
    check("unparseable settings are None: not the watch's to judge", reader.hooks() is None)
    check("the reader never writes", sorted(os.listdir(cfg)) == ["settings.json"])


def test_main_log_reader():
    print("\n== MainLogReader ==")
    d = tmpdir()
    log = write(os.path.join(d, "Logs", "main.log"), "old line 1\nold line 2\n")
    cursor = os.path.join(d, "state", "main-log-cursor.json")
    text, fresh = AD.MainLogReader(log, cursor).read_new()
    check("the first read is fresh and returns the log", fresh is True and "old line 2" in text, (text, fresh))
    with open(log, "a") as fh:
        fh.write("new line 3\n")
    text, fresh = AD.MainLogReader(log, cursor).read_new()
    check("the next read returns only what was appended", text == "new line 3\n" and fresh is False, (text, fresh))
    check("and an unchanged log returns nothing", AD.MainLogReader(log, cursor).read_new() == ("", False))
    write(log, "short\n")
    text, _ = AD.MainLogReader(log, cursor).read_new()
    check("a truncated log is read from its start", text == "short\n", text)
    os.rename(log, log + ".1")
    write(log, "rotated\n")
    text, fresh = AD.MainLogReader(log, cursor).read_new()
    check("a rotated log (a new file) is read from its start", text == "rotated\n" and fresh is False, (text, fresh))
    big = write(os.path.join(d, "Logs", "big.log"), "".join("line %04d xxxxxxxxxxxxxxxxxxxx\n" % i for i in range(400)))
    text, _ = AD.MainLogReader(big, os.path.join(d, "state", "big-cursor.json"), max_bytes=1000).read_new()
    check("a read is capped, starting at a whole line", 0 < len(text) <= 1000 and text.startswith("line ")
          and text.endswith("line 0399 xxxxxxxxxxxxxxxxxxxx\n"), text[:80])
    missing_cursor = os.path.join(d, "state", "missing-cursor.json")
    check("a missing log reads as nothing and leaves no cursor",
          AD.MainLogReader(os.path.join(d, "nope.log"), missing_cursor).read_new() == ("", False)
          and not os.path.exists(missing_cursor))


def main():
    global AD
    try:
        from events_core import adapters as AD
    except Exception as exc:
        check("events_core.adapters imports", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_snapshot, test_state_runner_files, test_session_id, test_alert_sink, test_git_probe,
                  test_claude_settings_hooks, test_main_log_reader):
            try:
                t()
            except Exception as exc:
                import traceback
                traceback.print_exc()
                check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
