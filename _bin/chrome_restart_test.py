#!/usr/bin/env python3
"""Tests for chrome_restart.py: it finds and restarts only the desktop Chrome, and only when safe.

The process table, the signals and the clock are fakes: no real Chrome is touched. The lock tests
run in a temporary BRAIN_STATE and only ever call `check`, never `restart`, on the real machine.
Run standalone: python3 _bin/chrome_restart_test.py
"""
import os
import signal
import subprocess
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["BRAIN_STATE"] = tempfile.mkdtemp(prefix="chrome-restart-test-")
os.environ.pop("BRAIN_ROUTINE_SCRATCH", None)
sys.path.insert(0, HERE)
import chrome_restart as CR  # noqa: E402
import task_locks  # noqa: E402
import browser_lock_test as BLT  # noqa: E402  (its fake Claude session)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def proc(pid, ppid, args, comm=None, joined=False):
    """A process table row. `joined` mimics Chrome's helpers: the whole command line in one arg."""
    a = args.split()
    return {"pid": pid, "ppid": ppid, "comm": comm or os.path.basename(a[0])[:15],
            "args": [args] if joined else a}


KEEP = proc(100, 50, "/bin/sh /home/user/.local/bin/chrome-keepalive.sh")
DESKTOP = proc(101, 100, "/opt/google/chrome/chrome --profile-directory=Default --no-first-run --no-default-browser-check")
ZYGOTE = proc(102, 101, "/opt/google/chrome/chrome --type=zygote --no-zygote-sandbox", joined=True)
RENDERER = proc(103, 102, "/opt/google/chrome/chrome --type=renderer --crashpad-handler-pid=9", joined=True)
CRASHPAD = proc(104, 1, "/opt/google/chrome/chrome_crashpad_handler --monitor-self --database=/x")
HOST = proc(105, 101, "/home/user/.local/bin/claude --chrome-native-host", comm="claude")
# a Playwright render launching /opt/google/chrome/chrome headless with its own profile
HEADLESS = proc(200, 199, "/opt/google/chrome/chrome --disable-field-trial-config --headless=new "
                          "--user-data-dir=/tmp/playwright_chromiumdev_profile-x --remote-debugging-pipe about:blank")
HEADLESS_OLD = proc(201, 199, "/opt/google/chrome/chrome --headless --no-sandbox about:blank")
HEADLESS_KID = proc(202, 200, "/opt/google/chrome/chrome --type=renderer --headless", joined=True)
# a Playwright browser with a window: automation flags and its own profile
PLAYWRIGHT = proc(210, 199, "/opt/google/chrome/chrome --enable-automation --user-data-dir=/tmp/pw-profile about:blank")
OTHER_PROFILE = proc(220, 1, "/opt/google/chrome/chrome --user-data-dir=/home/user/other-profile")
SAME_PROFILE = proc(230, 1, "/opt/google/chrome/chrome --user-data-dir=" + CR.PROFILE_DIR)
TABLE = [KEEP, DESKTOP, ZYGOTE, RENDERER, CRASHPAD, HOST, HEADLESS, HEADLESS_OLD, HEADLESS_KID, PLAYWRIGHT, OTHER_PROFILE]


def survey_tests():
    print("== telling the desktop Chrome apart ==")
    s = CR.survey(TABLE)
    check("the keepalive's chrome child is the desktop Chrome, and only it",
          [p["pid"] for p in s["desktop"]] == [101], [p["pid"] for p in s["desktop"]])
    check("the keepalive is found", [p["pid"] for p in s["keepalive"]] == [100])
    left = sorted(p["pid"] for p in s["others"])
    check("headless renders, Playwright and other profiles are reported as left alone",
          left == [200, 201, 210, 220], left)
    check("helpers whose command line Chrome joined into one string are recognised by their --type",
          not CR.is_desktop(RENDERER, {p["pid"]: p for p in TABLE}) and 103 not in left)
    s2 = CR.survey([p for p in TABLE if p is not KEEP and p is not DESKTOP] + [SAME_PROFILE])
    check("a Chrome on the default profile started by hand counts as the desktop one",
          [p["pid"] for p in s2["desktop"]] == [230] and not s2["keepalive"], s2["desktop"])
    s3 = CR.survey(TABLE + [SAME_PROFILE])
    check("with several candidates the keepalive's child wins", [p["pid"] for p in s3["desktop"]] == [101])


class FakeMachine:
    """A process table that reacts to signals and to time like the keepalive does."""

    def __init__(self, table, ignores_term=False, relaunch_after=6.0, keepalive=True):
        self.table = [dict(p) for p in table if keepalive or p is not KEEP]
        self.t = 0.0
        self.sent = []
        self.ignores_term = ignores_term
        self.relaunch_after = relaunch_after
        self.died_at = None

    def procs(self):
        if self.died_at is not None and self.relaunch_after is not None \
                and self.t >= self.died_at + self.relaunch_after \
                and not any(p["pid"] == 301 for p in self.table):
            self.table.append(proc(301, 100, "/opt/google/chrome/chrome --profile-directory=Default --no-first-run"))
        return [dict(p) for p in self.table]

    def kill(self, pid, sig):
        self.sent.append((pid, sig))
        if sig == signal.SIGTERM and self.ignores_term:
            return
        family = {pid}
        changed = True
        while changed:   # the browser takes its helpers down with it
            n = len(family)
            family |= {p["pid"] for p in self.table if p["ppid"] in family and CR.is_chrome(p)}
            changed = len(family) != n
        self.table = [p for p in self.table if p["pid"] not in family]
        if pid == 101:
            self.died_at = self.t

    def sleep(self, s):
        self.t += s

    def clock(self):
        return self.t

    def run(self, **kw):
        a = types.SimpleNamespace(grace=10, timeout=30, settle=5)
        for k, v in kw.items():
            setattr(a, k, v)
        return CR.restart(a, procs_fn=self.procs, kill=self.kill, sleep=self.sleep, clock=self.clock)


def restart_tests():
    print("\n== the restart, on a fake machine ==")
    m = FakeMachine(TABLE)
    rc = m.run()
    pids = {p["pid"] for p in m.table}
    check("restart signals only the desktop Chrome", {pid for pid, _ in m.sent} == {101}, m.sent)
    check("with SIGTERM, no SIGKILL when it exits", m.sent == [(101, signal.SIGTERM)], m.sent)
    check("headless renders and Playwright survive it", {200, 201, 202, 210, 220} <= pids, sorted(pids))
    check("it waits for the keepalive's new Chrome and exits 0", rc == 0 and 301 in pids, (rc, sorted(pids)))

    m = FakeMachine(TABLE, ignores_term=True)
    rc = m.run(grace=10)
    check("a Chrome that ignores SIGTERM gets SIGKILL after the grace",
          m.sent == [(101, signal.SIGTERM), (101, signal.SIGKILL)] and rc == 0, (m.sent, rc))

    m = FakeMachine(TABLE, relaunch_after=None)
    rc = m.run(timeout=30)
    check("no new Chrome within the timeout is exit 1", rc == 1, rc)

    m = FakeMachine(TABLE, keepalive=False)
    rc = m.run()
    check("without the keepalive it refuses with exit 3 and signals nothing", rc == 3 and not m.sent, (rc, m.sent))

    m = FakeMachine([p for p in TABLE if p is not DESKTOP], relaunch_after=3)
    m.died_at = 0.0
    rc = m.run()
    check("with no desktop Chrome up it just waits for the keepalive to start one",
          rc == 0 and not m.sent, (rc, m.sent))


def run_cli(*args, env=None):
    p = subprocess.run([sys.executable, os.path.join(HERE, "chrome_restart.py"), *args],
                       env=env or os.environ.copy(), capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + p.stderr


HOLD = ("import fcntl, sys, time\n"
        "fh = open(sys.argv[1], 'a+'); fcntl.flock(fh, fcntl.LOCK_EX)\n"
        "fh.seek(0); fh.truncate(); fh.write('tick-other pid 4242 since now\\n'); fh.flush()\n"
        "print('held', flush=True); time.sleep(float(sys.argv[2]))\n")


def safety_tests():
    print("\n== when a restart is allowed (temporary lock state, `check` only) ==")
    lock = task_locks.path("group-chrome")
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    rc, out = run_cli("check")
    check("lock free: allowed", rc == 0 and "lock group chrome free" in out, out)

    holder = subprocess.Popen([sys.executable, "-c", HOLD, lock, "30"], stdout=subprocess.PIPE, text=True)
    try:
        holder.stdout.readline()
        rc, out = run_cli("check")
        check("lock held by a routine or session that is not the caller: refused with 75 and the holder",
              rc == 75 and "tick-other" in out and "browser_lock.py hold" in out, out)
        called = []
        real = CR.restart
        CR.restart = lambda *a, **kw: called.append(a) or 0   # never the real one here
        try:
            rc = CR.cmd_restart(types.SimpleNamespace(grace=1, timeout=1, settle=0))
        finally:
            CR.restart = real
        check("restart refuses the same way before touching anything", rc == 75 and not called, (rc, called))
        rc, out = run_cli("check", env=dict(os.environ, BRAIN_ROUTINE_SCRATCH="/tmp/x"))
        check("inside a routine whose tasks.py does not hold it: refused, and told why",
              rc == 75 and "not by this routine" in out, out)
    finally:
        holder.kill()
        holder.wait()

    # this test process plays tasks.py: it holds the group and the command runs below it
    with task_locks.open_lock("group-chrome") as fh:
        task_locks.try_lock(fh)
        task_locks.mark(fh, "tick-routine")
        rc, out = run_cli("check", env=dict(os.environ, BRAIN_ROUTINE_SCRATCH="/tmp/x"))
        check("inside a routine whose tasks.py holds it: allowed", rc == 0 and "chrome mine" in out, out)
    env = os.environ.copy()
    session, res = BLT.fake_claude(env, [BLT.lock_cmd("hold", "--label", "s1", "--wait-minutes", "0.05"),
                                         [sys.executable, os.path.join(HERE, "chrome_restart.py"), "check"]],
                                   linger=30)
    try:
        check("a session that took `browser_lock.py hold` may restart", res[1][0] == 0 and "chrome mine" in res[1][1], res)
        rc, out = run_cli("check")
        check("another session may not while it holds it", rc == 75 and "session s1" in out, out)
    finally:
        session.kill()
        session.wait()
        BLT.run(env, "release", "--force")

    print("\n== a free lock is held for the restart itself ==")
    seen = {}
    real = CR.restart

    def fake_restart(a, **kw):
        with task_locks.open_lock("group-chrome") as other:
            seen["busy"] = not task_locks.try_lock(other)
        return 0
    CR.restart = fake_restart
    try:
        rc = CR.cmd_restart(types.SimpleNamespace(grace=1, timeout=1, settle=0))
    finally:
        CR.restart = real
    check("routines and sessions wait while it restarts", rc == 0 and seen.get("busy") is True, seen)
    with task_locks.open_lock("group-chrome") as fh:
        check("and the lock is free again afterwards", task_locks.try_lock(fh))


def main():
    survey_tests()
    restart_tests()
    safety_tests()
    print(f"\nRESULT: {len(ok)} passed, {len(fail)} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
