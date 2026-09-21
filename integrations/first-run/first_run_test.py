#!/usr/bin/env python3
"""Tests for first_run.py and setup.sh, the first run's entry points.

Both run as subprocesses with a scratch HOME and BRAIN_STATE and stdin that is not a terminal,
so nothing is asked and nothing on the real machine is touched. Run standalone:

    python3 integrations/first-run/first_run_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "first_run.py")
SETUP = os.path.join(HERE, "setup.sh")

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def main():
    root = tempfile.mkdtemp(prefix="first-run-cli-")
    try:
        if not (os.path.exists(CLI) and os.path.exists(SETUP)):
            check("first_run.py and setup.sh exist", False, (CLI, SETUP))
            print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
            return 1
        state = os.path.join(root, "state")
        env = {k: v for k, v in os.environ.items() if not k.startswith("BRAIN_")}
        # A forced machine key: the registration at the end of skip-all reads no real hardware.
        env.update(HOME=os.path.join(root, "home"), BRAIN_STATE=state, BRAIN_FAKE_SCHEDULER="1",
                   BRAIN_MACHINE_KEY="test-box-0000abcd")
        path = os.path.join(state, "first-run.json")

        def run(*args):
            p = subprocess.run([sys.executable, CLI] + list(args), env=env, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=60)
            return p.returncode, p.stdout, p.stderr

        rc, out, err = run("status")
        check("status on a machine with no first run exits 3 and lists every step as not asked",
              rc == 3 and out.count("not asked yet") == 9 and "remote_control" in out, (rc, out, err))
        rc, out, err = run("run")
        check("run without a terminal changes nothing and says how to run it",
              rc == 0 and not os.path.exists(path) and "setup.sh" in (out + err), (rc, out, err))
        p = subprocess.run(["bash", SETUP], env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        check("setup.sh without a terminal exits 0, writes nothing and says how to run it later",
              p.returncode == 0 and not os.path.exists(path) and "terminal" in (p.stdout + p.stderr),
              (p.returncode, p.stdout, p.stderr))
        rc, out, err = run("skip-all")
        data = json.load(open(path)) if os.path.exists(path) else {}
        steps = data.get("steps", {})
        files_dir = os.path.join(root, "home", "BrainFiles")
        config = os.path.join(state, "files-dir.json")
        check("skip-all creates and records the default files directory, which cannot be declined",
              rc == 0 and steps.get("files", {}).get("status") == "done" and steps["files"].get("dir") == files_dir
              and os.path.isdir(files_dir) and os.path.exists(config)
              and json.load(open(config)) == {"dir": files_dir}, (rc, out, err, data))
        check("and records every other step as declined, for CI and unattended machines",
              len(steps) == 9 and all(v["status"] == "declined" for k, v in steps.items() if k != "files"), steps)
        check("and registers this machine in the machine registry, under this machine's state",
              os.path.isfile(os.path.join(state, "machines", "test-box-0000abcd.json")),
              os.listdir(state))
        rc, out, err = run("status")
        check("after that status exits 0", rc == 0, (rc, out))
        rc, out, err = run("reset", "scheduler")
        rc2, out2, _ = run("status")
        check("reset makes one step ask again", rc == 0 and rc2 == 3 and "scheduler    not asked yet" in out2, (rc, out2))
        rc, out, err = run("reset", "remote_control")
        rc2, out2, _ = run("status")
        check("the Remote Control step can be asked again on its own",
              rc == 0 and rc2 == 3 and "remote_control not asked yet" in out2 and "scheduler    not asked yet" in out2,
              (rc, out2))
        rc, out, err = run("reset", "nonsense")
        check("reset of an unknown step is a usage error", rc == 2, (rc, err))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
