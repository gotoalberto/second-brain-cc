#!/usr/bin/env python3
"""Tests for browser_lock.py: a session holds a tasks.py lock group, others wait or are told.

Everything runs in a temporary BRAIN_STATE. Run standalone: python3 _bin/browser_lock_test.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


# The tests use a named group beside `chrome`, the way a set of routines sharing one account does.
GROUP = "social"


def with_group(args):
    """The command with `--group social` unless it names a group itself."""
    args = list(args)
    return args if "--group" in args or not args else args[:1] + ["--group", GROUP] + args[1:]


def run(env, *args):
    p = subprocess.run([sys.executable, os.path.join(HERE, "browser_lock.py"), *with_group(args)],
                       env=env, capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + p.stderr


# A stand in for a Claude session: python started through a symlink named `claude`, so its comm is
# `claude` and browser_lock.claude_ancestor() sees it as the session above the commands it runs.
# It runs each command, prints one JSON line with [rc, output] per command, then stays alive
# `linger` seconds (a session's hold lasts while the session lives).
FAKE_CLAUDE = r"""
import json, subprocess, sys, time
cmds = json.loads(sys.argv[1])
out = []
for c in cmds:
    p = subprocess.run(c, capture_output=True, text=True, timeout=60)
    out.append([p.returncode, p.stdout + p.stderr])
print(json.dumps(out), flush=True)
time.sleep(float(sys.argv[2]))
"""


def fake_claude(env, cmds, linger=0.0):
    """Start a fake Claude session running `cmds`; returns (process, results)."""
    d = tempfile.mkdtemp(prefix="fake-claude-")
    exe = os.path.join(d, "claude")
    os.symlink(sys.executable, exe)
    proc = subprocess.Popen([exe, "-c", FAKE_CLAUDE, json.dumps(cmds), str(linger)], env=env,
                            stdout=subprocess.PIPE, text=True)
    return proc, json.loads(proc.stdout.readline() or "[]")


def lock_cmd(*args):
    return [sys.executable, os.path.join(HERE, "browser_lock.py"), *with_group(args)]


def main():
    env = dict(os.environ, BRAIN_STATE=tempfile.mkdtemp(prefix="browser-lock-test-"))
    env.pop("BRAIN_ROUTINE_SCRATCH", None)
    print("== browser_lock ==")
    rc, out = run(env, "status")
    check("a fresh state reports the group free", rc == 0 and "free: lock group social" in out, out)
    check("status also covers the chrome group", "free: lock group chrome" in out, out)
    session, res = fake_claude(env, [lock_cmd("hold", "--label", "test-session", "--wait-minutes", "0.05"),
                                     lock_cmd("hold", "--label", "again", "--wait-minutes", "0.05")], linger=60)
    try:
        rc, out = res[0]
        check("hold takes social and chrome and returns", rc == 0 and "held: lock group chrome, social" in out, out)
        rc, out = res[1]
        check("a second hold by the same session is a no op", rc == 0 and "already held by this session" in out, out)
        rc, out = run(env, "status")
        check("status names the session holding it", rc == 75 and "session test-session" in out
              and "busy: lock group chrome" in out and "busy: lock group social" in out, out)
        rc, out = run(env, "hold", "--label", "other", "--wait-minutes", "0.1")
        check("a hold by another session waits, then says who holds it", rc == 75 and "test-session" in out, out)
        rc, out = run(env, "hold", "--group", "chrome", "--label", "other", "--wait-minutes", "0.05")
        check("--group chrome alone is the same lock", rc == 75 and "test-session" in out, out)
        rc, out = run(env, "release")
        check("release from outside the session refuses and says whose hold it is",
              rc == 75 and "not yours" in out, out)
        rc, out = run(env, "status")
        check("a refused release leaves the hold in place", rc == 75 and "test-session" in out, out)
        _, res2 = fake_claude(env, [lock_cmd("release")])
        rc, out = res2[0]
        check("release from another Claude session refuses too", rc == 75 and "another Claude session" in out, out)
        check("and the hold is still there afterwards", run(env, "status")[0] == 75, run(env, "status")[1])
        rc, out = run(dict(env, BRAIN_ROUTINE_SCRATCH="/tmp/x"), "hold")
        check("inside a routine hold takes nothing", rc == 0 and "inside a routine" in out, out)
        rc, out = run(dict(env, BRAIN_ROUTINE_SCRATCH="/tmp/x"), "hold", "--in-routine", "--wait-minutes", "0.05")
        check("inside a routine --in-routine takes the groups, so it waits for another holder",
              rc == 75 and "test-session" in out, out)
        sys.path.insert(0, HERE)
        os.environ["BRAIN_STATE"] = env["BRAIN_STATE"]
        import tasks as T
        T.STATE_DIR = type(T.STATE_DIR)(env["BRAIN_STATE"])
        T.RUNNER_LOG = os.path.join(env["BRAIN_STATE"], "runner.log")
        T.log = lambda path, msg: open(T.RUNNER_LOG, "a").write(msg + "\n")
        subprocess.Popen(["sh", "-c", f"sleep 3; {sys.executable} {os.path.join(HERE, 'browser_lock.py')} release --force"], env=env)
        t0 = time.monotonic()
        with T.group_locks(["chrome"], "tick-x"):
            waited = time.monotonic() - t0
        check("a routine in group chrome waits for the session and starts once it releases",
              waited >= 2, waited)
    finally:
        session.kill()
        session.wait()
    rc, out = run(env, "status")
    check("after the routine both groups are free again", rc == 0 and "busy" not in out, out)
    rc, out = run(env, "release")
    check("release with nothing held is harmless", rc == 0, out)
    session, res = fake_claude(env, [lock_cmd("hold", "--label", "mine", "--wait-minutes", "0.05"),
                                     lock_cmd("release")], linger=5)
    rc, out = res[1]
    check("the session that took the hold releases it", rc == 0 and "released lock group chrome, social" in out, out)
    check("and both groups are free right away", run(env, "status")[0] == 0, run(env, "status")[1])
    session.kill()
    session.wait()
    session, res = fake_claude(env, [lock_cmd("hold", "--label", "short", "--wait-minutes", "0.05")])
    session.wait()
    t0 = time.monotonic()
    while time.monotonic() - t0 < 25 and run(env, "status")[0] != 0:
        time.sleep(1)
    check("a session's hold ends by itself when the session ends", run(env, "status")[0] == 0, run(env, "status")[1])

    print(f"\nRESULT: {len(ok)} passed, {len(fail)} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
