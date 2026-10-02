#!/usr/bin/env python3
"""Tests for the Stop memory gate (gate_memory.py) in an unattended run.

The gate runs in a subprocess whose BRAIN_STATE, BRAIN_VAULT, HOME and TMPDIR are temporary
directories and whose BRAIN_OFFLINE is set, so nothing reaches the real Brain state or vault.
Run standalone:

    python3 _bin/gate_memory_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "gate_memory.py")

ok, fail = [], []

SID = "0f0f0f0f-0000-4000-8000-000000000001"

SEED = r'''
import sys
sys.path.insert(0, %(bin)r)
import brainlib as B
con = B.db()
con.execute("INSERT INTO sessions(sid, cwd, turns, wrote) VALUES (?, ?, ?, 0)",
            (B.sid8(%(sid)r), %(cwd)r, %(turns)d))
con.commit()
con.close()
'''


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail and not cond else ""))


def scratch(root):
    paths = {n: os.path.join(root, n) for n in ("home", "state", "vault")}
    for p in paths.values():
        os.makedirs(p)
    os.makedirs(os.path.join(paths["vault"], "_index"))
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": paths["home"], "TMPDIR": root,
           "BRAIN_STATE": paths["state"], "BRAIN_VAULT": paths["vault"], "BRAIN_OFFLINE": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "GIT_CEILING_DIRECTORIES": root,
           "LANG": os.environ.get("LANG", "C.UTF-8")}
    return env, paths


def seeded(root, turns):
    """A session with `turns` turns and nothing saved: long overdue for the gate."""
    env, paths = scratch(root)
    seed = SEED % {"bin": HERE, "sid": SID, "cwd": paths["home"], "turns": turns}
    subprocess.run([sys.executable, "-c", seed], env=env, check=True, capture_output=True, timeout=60)
    return env, paths


def stop(env, paths):
    payload = {"session_id": SID, "hook_event_name": "Stop", "cwd": paths["home"]}
    return subprocess.run([sys.executable, GATE], input=json.dumps(payload), env=env,
                          capture_output=True, text=True, timeout=60)


def main():
    print("== the gate blocks an interactive session that saved nothing ==")
    root = tempfile.mkdtemp(prefix="brain-gate-memory-test-")
    try:
        env, paths = seeded(root, turns=10)
        r = stop(env, paths)
        check("ten turns with nothing saved ask for a save", r.returncode == 2 and "/save" in r.stderr,
              (r.returncode, r.stderr[-300:]))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("== a scheduled run is never asked to save ==")
    # The runner tells a scheduled run not to save, and the extra turn this gate forces
    # replaces the run's final answer, which is where the runner reads the success marker.
    root = tempfile.mkdtemp(prefix="brain-gate-memory-test-")
    try:
        env, paths = seeded(root, turns=10)
        env["BRAIN_HEADLESS"] = "1"
        r = stop(env, paths)
        check("BRAIN_HEADLESS=1 lets the turn end", r.returncode == 0, (r.returncode, r.stderr[-300:]))
        check("and prints nothing that could block or replace the answer",
              r.stdout.strip() == "" and r.stderr.strip() == "", (r.stdout, r.stderr))
        check("and leaves no gate marker behind",
              not os.path.exists(os.path.join(paths["state"], "%s.memgate" % SID[:8])),
              os.listdir(paths["state"]))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print()
    print("RESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
