#!/usr/bin/env python3
"""Tests that every script finds Brain's state in the same place, before and after migration.

brainlib.STATE (and so kp.py, which takes it from brainlib), tasks.py and the launchd log
paths must agree: the legacy ~/.claude/state/brain while it is still a real directory, the
new ~/Library/Application Support/brain once migrate_state.py has linked it (or on a fresh
machine), BRAIN_STATE when set. Each probe is a subprocess with HOME temporary. Run
standalone:

    python3 _bin/state_location_test.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

ok, fail = [], []
TMP = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def world():
    root = tempfile.mkdtemp(prefix="state-location-")
    TMP.append(root)
    home = os.path.join(root, "home")
    os.makedirs(home)
    legacy = os.path.join(home, ".claude", "state", "brain")
    sys.path.insert(0, HERE)
    import brain_paths
    new = brain_paths.state_dir(environ={}, home=home)          # this platform's default
    env = dict(os.environ, HOME=home, BRAIN_KP_DB=os.path.join(root, "no.kdbx"),
               BRAIN_VAULT=os.path.join(root, "vault"))
    for k in ("BRAIN_STATE", "BRAIN_KP_STATE"):
        env.pop(k, None)
    return home, legacy, new, env


def probe(env, code):
    p = subprocess.run([sys.executable, "-c", code], cwd=HERE, env=env, capture_output=True, text=True, timeout=60)
    return p.stdout.strip().splitlines(), p.stderr


CODE = ("import brainlib, tasks, kp\n"
        "print(brainlib.STATE); print(brainlib.LOGS); print(tasks.STATE_DIR); print(tasks.STATE_FILE); "
        "print(tasks.LOG_DIR); print(kp.STATE)")


def expect(lines, state):
    return lines == [state, os.path.join(state, "logs"), state, os.path.join(state, "tasks-state.json"),
                     os.path.join(state, "logs", "tasks"), state]


def main():
    home, legacy, new, env = world()
    os.makedirs(legacy)
    lines, err = probe(env, CODE)
    check("with the legacy directory still real, brainlib, tasks.py and kp.py all use it", expect(lines, legacy),
          (lines, err[-300:]))

    home, legacy, new, env = world()
    os.makedirs(new)
    os.makedirs(os.path.dirname(legacy))
    os.symlink(new, legacy)
    lines, err = probe(env, CODE)
    check("after migration (legacy linked to the new directory) they all use the new one", expect(lines, new),
          (lines, err[-300:]))

    home, legacy, new, env = world()
    lines, err = probe(env, CODE)
    check("on a fresh machine they all use the new directory", expect(lines, new), (lines, err[-300:]))

    home, legacy, new, env = world()
    os.makedirs(legacy)
    custom = os.path.join(home, "custom-state")
    lines, err = probe(dict(env, BRAIN_STATE=custom), CODE)
    check("BRAIN_STATE moves all of them at once", expect(lines, custom), (lines, err[-300:]))

    for label in ("com.secondbrain.sync", "com.secondbrain.tasks"):
        text = open(os.path.join(HERE, label + ".plist")).read()
        check("%s logs under the new state directory, not ~/.claude" % label,
              "/home/brain-origin/Library/Application Support/brain/logs/" in text and "/.claude/state/brain" not in text,
              [l.strip() for l in text.splitlines() if "Path" in l])
    return finish()


def finish():
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
