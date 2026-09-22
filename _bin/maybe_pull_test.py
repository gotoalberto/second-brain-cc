#!/usr/bin/env python3
"""Tests for brainlib.maybe_pull, the one vault pull shared by retrieve.py and compass.py.

retrieve.py pulls unforced on every prompt (throttled by PULL_EVERY); compass.py pulls forced
and time-bounded once at SessionStart. Both must be the same code, and the forced call must keep
every safety the unforced one has. Each functional case runs in a subprocess whose BRAIN_VAULT,
BRAIN_STATE, HOME and TMPDIR are scratch directories, with no remote configured, so nothing
reaches the network or the real vault. Run standalone:

    python3 _bin/maybe_pull_test.py
"""
import os
import shutil
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
    d = tempfile.mkdtemp(prefix="brain-maybe-pull-test-")
    TMP.append(d)
    return d


def scratch():
    root = tmpdir()
    paths = {n: os.path.join(root, n) for n in ("home", "state", "vault")}
    for p in paths.values():
        os.makedirs(p)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": paths["home"], "TMPDIR": root,
           "BRAIN_STATE": paths["state"], "BRAIN_VAULT": paths["vault"],
           "PYTHONDONTWRITEBYTECODE": "1", "GIT_CEILING_DIRECTORIES": root,
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return env, paths


def py(code, env):
    return subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r)\n%s" % (HERE, code)],
                          env=env, capture_output=True, text=True, timeout=60)


def source(name):
    with open(os.path.join(HERE, name), errors="replace") as fh:
        return fh.read()


def test_one_implementation():
    rt, bl, cp = source("retrieve.py"), source("brainlib.py"), source("compass.py")
    check("the foreign rebase guard lives in brainlib", "pull-skipped-foreign-rebase" in bl)
    check("retrieve.py's per-prompt pull is brainlib's, not a second copy",
          "maybe_pull = B.maybe_pull" in rt and "def maybe_pull(" not in rt)
    check("compass.py pulls at SessionStart, forced and time-bounded",
          "B.maybe_pull(force=True, timeout=3)" in cp)
    import brainlib as B
    import retrieve
    check("retrieve.maybe_pull still answers, as the same function",
          retrieve.maybe_pull is B.maybe_pull)


def test_forced_pull_leaves_foreign_rebase():
    env, paths = scratch()
    os.makedirs(os.path.join(paths["vault"], ".git", "rebase-merge"))
    p = py("import brainlib as B\nB.maybe_pull(force=True)\nprint('ran')", env)
    check("a forced pull still leaves a foreign rebase untouched",
          p.returncode == 0 and "ran" in p.stdout
          and os.path.isdir(os.path.join(paths["vault"], ".git", "rebase-merge")),
          (p.stdout + p.stderr)[-300:])
    log = os.path.join(paths["state"], "logs", "sync.log")
    body = open(log, errors="replace").read() if os.path.isfile(log) else ""
    check("and the skip leaves a trace in the sync log", "pull-skipped-foreign-rebase" in body, body[-200:])
    check("and no last_pull marker from a call that never reached the pull",
          not os.path.exists(os.path.join(paths["state"], "last_pull")))


def git(env, *args):
    return subprocess.run(["git", "-C", env["BRAIN_VAULT"]] + list(args), env=env,
                          capture_output=True, text=True, timeout=30)


def test_force_bypasses_throttle():
    env, paths = scratch()
    vault = paths["vault"]
    subprocess.run(["git", "init", "-q", vault], env=env, capture_output=True)
    git(env, "config", "user.email", "test@example.com")
    git(env, "config", "user.name", "test")
    os.makedirs(os.path.join(vault, "30-Knowledge"))
    with open(os.path.join(vault, "30-Knowledge", "x.md"), "w") as fh:
        fh.write("---\ntitle: x\n---\n")
    git(env, "add", "-A")
    git(env, "commit", "-q", "-m", "seed")
    marker = os.path.join(paths["state"], "last_pull")
    open(marker, "w").close()                          # "a pull just happened"
    before = os.path.getmtime(marker)
    time.sleep(1.1)                                    # mtime resolution can be 1 s
    p1 = py("import brainlib as B\nB.maybe_pull()\nprint('ran')", env)
    check("an unforced call inside the throttle window does not pull",
          "ran" in p1.stdout and os.path.getmtime(marker) == before, (p1.stdout + p1.stderr)[-300:])
    p2 = py("import brainlib as B\nB.maybe_pull(force=True, timeout=3)\nprint('ran')", env)
    check("force=True re-attempts (and re-marks) inside the same window an unforced call skips",
          "ran" in p2.stdout and os.path.getmtime(marker) > before, (p2.stdout + p2.stderr)[-300:])


def main():
    for t in (test_one_implementation, test_forced_pull_leaves_foreign_rebase, test_force_bypasses_throttle):
        try:
            t()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    return finish()


def finish():
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
